# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2026 Mikhail Nevskiy
"""The window with the real Backend on the fake link (needs a display:
tests/run.sh gives it broadwayd). What is checked is what the window shows
and what was asked of MAX."""
import os
import time

from common import load, ok

bm = load()
from fake_hands import FakeHands  # noqa: E402
from fake_link import FakeLink, audio, file, now_ms, photo, video  # noqa: E402
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

SHOTS = os.environ.get("B8K_SHOTS")  # a directory to save screenshots in, if set


def spin(sec=0.0):
    """Let the window and the MAX thread work for a while."""
    end = time.monotonic() + sec
    ctx = GLib.MainContext.default()
    while True:
        while ctx.iteration(False):
            pass
        if time.monotonic() >= end:
            break
        time.sleep(0.01)


def wait(cond, sec=5.0, what="condition"):
    end = time.monotonic() + sec
    while not cond():
        assert time.monotonic() < end, "timed out waiting for " + what
        spin(0.02)


def shot(name):
    if not SHOTS:
        return
    import cairo
    spin(0.4)
    alloc = app.win.get_allocation()
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, alloc.width, alloc.height)
    app.win.draw(cairo.Context(surf))
    surf.write_to_png(os.path.join(SHOTS, name))


def walk(w):
    yield w
    if isinstance(w, Gtk.Container):
        for c in w.get_children():
            yield from walk(c)


def share_of(hold):
    """The ↪ beside a bubble, and whether it is left of it."""
    side = hold.get_child()
    kids = side.get_children()
    share = [b for b in kids if isinstance(b, Gtk.Button) and b.get_style_context().has_class("share")][0]
    return share, kids.index(share) == 0


def saves_of(w):
    """The save buttons inside a widget, in order."""
    return [b for b in walk(w) if isinstance(b, Gtk.Button) and b.get_style_context().has_class("save")]


def buttons(w):
    return [b for b in walk(w) if isinstance(b, Gtk.Button)]


def rows():
    """The chat ids the list shows, top to bottom."""
    shown = [r for r in app.list.get_children() if r.get_child_visible()]
    return [r.chat_id for r in sorted(shown, key=lambda r: r.get_index())]


def holds_of(v):
    return [w for w in walk(v.widget) if getattr(w, "msg_id", None) is not None]


def column(v):
    return ["day" if getattr(w, "is_day", False) else w.msg_id for w in walk(v.widget)
            if getattr(w, "is_day", False) or getattr(w, "msg_id", None) is not None]


def chips(v, msg_id):
    hold = [w for w in holds_of(v) if w.msg_id == msg_id][0]
    return [b for b in walk(hold) if isinstance(b, Gtk.Button) and b.get_style_context().has_class("react")]


def adj_of(v):
    """The chat's scrolling, as its ScrolledWindow has it."""
    return [w for w in walk(v.widget) if isinstance(w, Gtk.ScrolledWindow)][0].get_vadjustment()


def down_of(v):
    """The chat's down button, if shown."""
    found = [b for b in walk(v.widget) if isinstance(b, Gtk.Button)
             and b.get_style_context().has_class("down") and b.get_visible()]
    return found[0] if found else None


def menu_items():
    """The labels and buttons of the menu open now."""
    return {b.get_label(): b for b in walk(app.menu) if isinstance(b, Gtk.Button)}


def at_bottom(v):
    adj = adj_of(v)
    return adj.get_value() + adj.get_page_size() >= adj.get_upper() - 60


# --- MAX as the tests have it -----------------------------------------------------------
fake = FakeLink()
MAMA, PETYA, SPAM = 10, 20, 30
fake.person(MAMA, "Мама", contact=True)
fake.person(PETYA, "Петя", contact=True)
fake.person(SPAM, "Спамер")
fake.person(40, "Ольга", phone="+79001234567")
mama = fake.dialog(MAMA)
spam = fake.dialog(SPAM)
dacha = fake.group(-12, "Дача", members=[PETYA])
news = fake.group(-31, "Новости города", kind="CHANNEL", unread=4)
fake.group(-70, "Погода", kind="CHANNEL", joined=False, link="https://max.ru/weather")
t0 = now_ms() - 3 * 86400000
fake.say(mama, "Привет! Как дела?", MAMA, t=t0, reactions=[("👍", 2)])
fake.say(mama, "Хорошо", t=t0 + 1000)
fake.say(spam, "Акция!", SPAM, t=t0 + 2000)
fake.say(dacha, "Фото с участка", PETYA, t=t0 + 3000)
fake.say(news, "Перекрытие улицы", t=t0 + 4000)

bm.save_json(bm.KNOWN, [MAMA, PETYA])  # not the first run: the stranger is not known
hands = FakeHands()
app = bm.Max(link=fake, media=bm.Media(hands.spawn, hands.open_uri, hands.fetch, hands.player,
                                       hands.download))
def no_dialog(*_a):  # a real save dialog would wait for a person: never in a test
    raise AssertionError("an unexpected save dialog")


real_ask_save_path = app.ask_save_path
app.ask_save_path = no_dialog
questions = []  # b8k-compat's ask, answered here: yes unless `answer` says otherwise
answer = [True]
bm.dialogs.ask = lambda parent, question, yes, *a: questions.append((question, yes)) or answer[0]
buzzes = []  # new messages the desktop was told of (notifications)
_notify = app.notify
app.notify = lambda msg: buzzes.append(msg)
badges = []  # the counts sent as Unity's LauncherEntry
_badge = app.badge
app.badge = lambda n: (badges.append(n), _badge(n))
app.register(None)
app.do_activate()
wait(lambda: app.chatlist.chats and app.backend.me, what="login")
spin(0.3)

# --- the list: tabs, strangers hidden, channels quiet --------------------------------------
assert rows() == [dacha, mama], rows()  # the stranger's dialog is hidden, channels elsewhere
assert app.tab_channels.get_label() == "Каналы · 4"
app.tab_channels.set_active(True)
spin(0.1)
assert rows() == [news]
app.tab_chats.set_active(True)
spin(0.1)
assert app.invites_switch.get_active() and not app.invites_switch.get_sensitive()
assert "официальном приложении" in app.invites_card.get_children()[1].get_text()
shot("list.png")
ok("list")

# --- incoming: a notification from a contact, none from a stranger or a channel ---------------
row_before = app.rows[mama]
buzzes.clear()
fake.incoming(spam, "Купите", SPAM)
spin(0.3)
assert not buzzes and spam not in rows()
fake.incoming(news, "Срочно", 50)
spin(0.3)
assert not buzzes
fake.incoming(mama, "Позвони вечером", MAMA)
wait(lambda: buzzes, what="notification")
assert buzzes[-1]["text"] == "Позвони вечером" and buzzes[-1]["chat"] == mama
sent = []
app.send_notification = lambda key, note: sent.append((key, note))
_notify(buzzes[-1])
assert sent and sent[-1][0] == "chat-%d" % mama
# what goes to the desktop: a sender's markup escaped, no control characters
title, body = bm.note_text({"title": "Да\x1b[31mча", "type": "CHAT"},
                           {"text": '<a href="https://evil.example">жми</a>\x07<img src="/etc/x">',
                            "photos": [], "who": "<b>Петя</b>"})
assert "\x1b" not in title and "\x07" not in body
assert "<" not in body and "&lt;a href" in body and "&lt;b&gt;Петя" in body, body
assert badges and badges[-1] == app.chatlist.counts()["loud"] > 0
assert rows()[0] == mama and app.rows[mama] is row_before  # the row is kept, redrawn
app.on_contacts_only(False)
spin(0.1)
assert spam in rows()
app.on_contacts_only(True)
spin(0.1)
ok("incoming")

# --- pinning and notifications ---------------------------------------------------------------
app.toggle_pin(app.chatlist.get(dacha))  # the rules are test_chatlist's: here, that rows follow
spin(0.1)
assert rows()[0] == dacha and "📌" in "".join(
    w.get_text() for w in walk(app.rows[dacha]) if isinstance(w, Gtk.Label))
app.toggle_pin(app.chatlist.get(dacha))
app.toggle_mute(app.chatlist.get(news))  # a channel: notifications on
buzzes.clear()
fake.incoming(news, "Новость", 50)
wait(lambda: buzzes, what="channel buzz")
app.toggle_mute(app.chatlist.get(news))
spin(0.1)
row = app.rows[mama]
app.row_menu(None, 5, row.get_allocation().y + 5)
spin(0.1)
app.on_row(app.list, row)  # the release of the long press opens nothing
assert app.stack.get_visible_child_name() == "chats"
app.held = 0
ok("pins, notifications")

# --- a chat: reactions, renaming, the scroll rules ----------------------------------------------
app.open(mama)
wait(lambda: app.view and len(holds_of(app.view)) == 3, what="mama's chat")
v = app.view
first = fake.msgs[mama][0].id
assert [b.get_label() for b in chips(v, first)] == ["👍 2"]
app.pick_reaction(mama, first, holds_of(v)[0].get_child())
spin(0.1)
app.react(mama, first, "❤️")
wait(lambda: len(chips(v, first)) == 2, what="reaction")
assert [b.get_label() for b in chips(v, first)] == ["👍 2", "❤️ 1"]
assert chips(v, first)[1].get_style_context().has_class("yours")
shot("reactions.png")
fake.counts = False  # MAX answers without counts: the window counts
chips(v, first)[1].clicked()
wait(lambda: len(chips(v, first)) == 1, what="reaction off")
assert fake.asked("react")[-1]["emoji"] is None
fake.counts = True
fake.reaction(mama, first, [("👍", 3), ("😂", 1)])
wait(lambda: len(chips(v, first)) == 2, what="someone's reaction")
assert [b.get_label() for b in chips(v, first)] == ["👍 3", "😂 1"]
app.edit.clicked()  # the chat's menu: rename, pin, notifications, delete
spin(0.1)
assert list(menu_items()) == ["✏️ Переименовать", "📌 Закрепить сверху", "🔕 Без оповещений",
                              "🗑 Удалить переписку"], list(menu_items())
shot("chat-menu.png")
menu_items()["✏️ Переименовать"].clicked()
assert app.naming.get_visible()
app.name_entry.set_text("  Мамочка ")
app.rename()
wait(lambda: app.title.get_text() == "Мамочка", what="rename")
assert app.chatlist.get(mama)["title"] == "Мамочка"
app.edit.clicked()
menu_items()["📌 Закрепить сверху"].clicked()
assert app.chatlist.is_pinned(mama)
app.edit.clicked()
menu_items()["🔕 Без оповещений"].clicked()
assert app.chatlist.quiet(mama)
app.edit.clicked()
assert "📌 Открепить" in menu_items() and "🔔 Включить оповещения" in menu_items()
menu_items()["📌 Открепить"].clicked()
app.edit.clicked()
menu_items()["🔔 Включить оповещения"].clicked()
assert not app.chatlist.is_pinned(mama) and not app.chatlist.quiet(mama)
ok("reactions, rename, chat menu")

# --- forwarding a message ---------------------------------------------------------------------
app.pick_reaction(mama, first, holds_of(v)[0].get_child())
spin(0.1)
assert not [k for k in menu_items() if "Переслать" in k or "Сохранить" in k]  # reactions only
app.menu.popdown()
share, left = share_of(holds_of(v)[0])  # Мама's message: the ↪ right of it
assert not left and share.get_valign() == Gtk.Align.END
assert share.get_image().get_icon_name()[0] == "mail-forward-symbolic"
mine = [h for h in holds_of(v) if v.message(h.msg_id)["mine"]][0]
assert share_of(mine)[1]  # an own message: the ↪ left of it
shot("share.png")
share.clicked()
spin(0.1)
assert app.stack.get_visible_child_name() == "forward" and app.title.get_text() == "Переслать"
targets = [r.chat_id for r in app.fwd_list.get_children()]
assert dacha in targets and mama in targets and news not in targets  # no channels
app.fwd_entry.set_text("дач")
wait(lambda: [r.chat_id for r in app.fwd_list.get_children()] == [dacha], what="forward search")
shot("forward.png")
answer[0] = False  # asked first: «no» keeps choosing
app.fwd_list.emit("row-activated", app.fwd_list.get_children()[0])
spin(0.1)
assert questions[-1] == ("Переслать сообщение в «Дача»?", "Переслать")
assert app.stack.get_visible_child_name() == "forward" and not fake.asked("forward")
answer[0] = True
app.fwd_list.emit("row-activated", app.fwd_list.get_children()[0])
wait(lambda: app.open_chat == dacha, what="forwarded, and in that chat")
assert app.stack.get_visible_child_name() == "chat"
assert fake.asked("forward")[-1] == {"chat_id": dacha, "msg_id": first, "from_chat_id": mama}
assert app.chatlist.get(dacha)["last"].startswith("Вы: ↪ Привет! Как дела?")
wait(lambda: any("Переслано от" in w.get_text() for w in walk(app.view.widget)
                 if isinstance(w, Gtk.Label)), what="forwarded bubble")
fwd = [w.get_text() for w in walk(app.view.widget) if isinstance(w, Gtk.Label)]
assert "↪ Переслано от Мамочка" in fwd and "Привет! Как дела?" in fwd, fwd
app.open(mama)
spin(0.2)
ok("forward")

# --- a message deleted for everyone by its sender: gone here too --------------------------------
doomed = fake.incoming(mama, "Ой, не тебе", MAMA)
wait(lambda: any(w.msg_id == doomed.id for w in holds_of(app.view)), what="the message to delete")
assert app.chatlist.get(mama)["last"] == "Ой, не тебе"
fake.deleted(mama, [doomed.id])
wait(lambda: not any(w.msg_id == doomed.id for w in holds_of(app.view)), what="deleted bubble")
wait(lambda: app.chatlist.get(mama)["last"] != "Ой, не тебе", what="list preview")
assert doomed.id not in [m["id"] for m in bm.cache_read(mama)]
col = column(app.view)
assert all(not (a == b == "day") for a, b in zip(col, col[1:])) and col[-1] != "day"
ok("deleted for everyone")

# --- emoji into the message ---------------------------------------------------------------------
app.entry.set_text("Привет ")
app.entry.set_position(-1)
app.smile.set_active(True)
spin(0.1)
assert app.emoji_pop is not None and not app.emoji_pop.get_modal()  # the entry keeps the focus
panel = [b for b in walk(app.emoji_pop) if isinstance(b, Gtk.Button)]
names = [w.get_text() for w in walk(app.emoji_pop) if isinstance(w, Gtk.Label)
         and w.get_style_context().has_class("emoji-group")]
assert names == ["Лица", "Жесты", "Сердца", "Разное"]  # nothing recent yet
smiley = [b for b in panel if b.get_label() == "😀"][0]
heart = [b for b in panel if b.get_label() == "❤️"][0]
smiley.clicked()
heart.clicked()
assert app.entry.get_text() == "Привет 😀❤️" and app.emoji_pop is not None  # stays open for more
app.entry.set_position(0)
smiley.clicked()
assert app.entry.get_text() == "😀Привет 😀❤️"
assert bm.load_json(bm.EMOJI_RECENT, []) == ["😀", "❤️"]
shot("emoji.png")
app.smile.set_active(False)
spin(0.1)
assert app.emoji_pop is None
app.smile.set_active(True)
spin(0.1)
assert [w.get_text() for w in walk(app.emoji_pop) if isinstance(w, Gtk.Label)
        and w.get_style_context().has_class("emoji-group")][0] == "Недавние"
app.send()
wait(lambda: app.entry.get_text() == "", what="sent with emoji")
assert fake.asked("send")[-1] == {"chat_id": mama, "text": "😀Привет 😀❤️"}
assert not app.smile.get_active() and app.emoji_pop is None
ok("emoji")

# --- search: a person by phone, then a channel by link -----------------------------------------
app.show_list()
app.show_find()
app.find_entry.set_text("8 900 123 45 67")
app.find()
wait(lambda: len(buttons(app.found)) == 2, what="person card")
write, add = buttons(app.found)
add.clicked()
wait(lambda: add.get_label() == "В контактах", what="added")
assert 40 in fake.contacts
write.clicked()
spin(0.2)
olga = fake.me.id ^ 40
assert app.open_chat == olga and app.title.get_text() == "Ольга"
app.entry.set_text("Здравствуйте")
app.send()
wait(lambda: app.chatlist.listed(olga), what="new dialog")
assert fake.asked("send")[-1] == {"chat_id": olga, "text": "Здравствуйте"}
assert [w.msg_id for w in holds_of(app.view)] == [fake.msgs[olga][-1].id]
app.show_list()
app.show_find()
app.find_entry.set_text("@weather")
app.find()
wait(lambda: buttons(app.found), what="channel card")
join = buttons(app.found)[0]
assert join.get_label() == "Подписаться"
join.clicked()
wait(lambda: app.open_chat == -70, what="joined")
assert not app.inputbar.get_visible()
app.edit.clicked()
menu_items()["🚪 Отписаться от канала"].clicked()
assert app.confirm_yes.get_label() == "Отписаться"
app.confirm_yes.clicked()
wait(lambda: app.stack.get_visible_child_name() == "chats", what="left")
assert fake.asked("leave")[-1] == {"chat_id": -70} and not app.chatlist.listed(-70)
ok("search, join, leave")

# --- a long chat: pages as the reader scrolls up, a spinner, cut on leaving -------------------
big = fake.group(-50, "Большая", members=[PETYA])
tb = now_ms() - 10 * 86400000
for i in range(200):
    fake.say(big, "сообщение %d" % i, PETYA, t=tb + i * 600000)  # ten-minute steps: two days
fake.incoming(big, "последнее", PETYA)
wait(lambda: app.chatlist.listed(big), what="big chat")
bm.PREFETCH = 0  # only the reader's scrolling fetches here
app.open(big)
wait(lambda: len(holds_of(app.view)) >= bm.PAGE, what="first page")
v = app.view
assert at_bottom(v)
spinner_seen = False
for _ in range(15):
    adj_of(v).set_value(0)
    for _ in range(25):  # a page comes and is built once scrolling rests
        spin(0.1)
        spinner_seen = spinner_seen or any(isinstance(w, Gtk.Spinner) and w.get_mapped()
                                           and w.props.active for w in walk(v.widget))
    if len(holds_of(v)) >= 180:
        break
assert len(holds_of(v)) >= 180, len(holds_of(v))
assert spinner_seen
ids = [w.msg_id for w in holds_of(v)]
assert ids == sorted(ids, key=lambda i: [m.id for m in fake.msgs[big]].index(i))
col = column(v)
assert col[0] == "day" and all(not (a == b == "day") for a, b in zip(col, col[1:]))
shot("older.png")
app.show_list()
spin(0.1)
assert len(holds_of(v)) == bm.BUBBLES and column(v)[0] == "day"
assert holds_of(v)[-1].msg_id == fake.msgs[big][-1].id
ok("pages, spinner, cut")

# --- the place: kept when coming back; another's message stays put, the own goes down ---------
app.open(big)
spin(0.5)
adj = adj_of(v)
assert down_of(v)  # back where it was left, up among older ones
down_of(v).clicked()
wait(lambda: at_bottom(v) and down_of(v) is None, what="down button gone at the bottom")
adj.set_value(adj.get_upper() / 3)
spin(0.2)
place = adj.get_value()
app.show_list()
app.open(big)
spin(0.5)
assert abs(adj.get_value() - place) < 5, (adj.get_value(), place)
assert down_of(v) and down_of(v).get_label() == "↓"
fake.incoming(big, "чужое", PETYA)
spin(0.5)
assert abs(adj.get_value() - place) < 5
assert down_of(v).get_label() == "↓ 1"  # one came while reading up there
shot("down.png")
down_of(v).clicked()
wait(lambda: at_bottom(v) and down_of(v) is None, what="down to the newest")
adj.set_value(adj.get_upper() / 3)
spin(0.3)
app.entry.set_text("своё")
app.send()
wait(lambda: at_bottom(v), what="own message at the bottom")
ok("scroll rules")

# --- a photo full screen: a tap opens it, another closes it ----------------------------------------
from gi.repository import GdkPixbuf  # noqa: E402
_pix = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 400, 300)
_pix.fill(0x3584e4ff)
hands.photo_bytes = _pix.save_to_bufferv("png", [], [])[1]
pic = fake.incoming(mama, "Наша дача", MAMA, attaches=[photo("https://i.oneme.ru/dacha.png")])
app.show_list()
app.open(mama)
wait(lambda: any(w.msg_id == pic.id for w in holds_of(app.view)), what="photo message")
frame = [w for w in walk(app.view.widget) if getattr(w, "photo_url", None) == "https://i.oneme.ru/dacha.png"][0]
app.view.held_at = time.monotonic()  # the release of a long press is no tap
frame.tap.emit("released", 1, 5.0, 5.0)
spin(0.1)
assert app.stack.get_visible_child_name() == "chat"
app.view.held_at = 0
frame.tap.emit("released", 1, 5.0, 5.0)
wait(lambda: app.viewer_image.get_pixbuf() is not None, what="photo full screen")
assert app.stack.get_visible_child_name() == "photo"
# within the window: its header stays (back, «Фото», save), no full screen
assert app.win.get_titlebar().get_visible() and app.title.get_text() == "Фото"
assert app.back.get_visible() and app.viewer_save.get_visible()
assert not app.win.get_window().get_state() & Gdk.WindowState.FULLSCREEN
alloc = app.viewer.get_allocation()
shown = app.viewer_image.get_pixbuf()
assert abs(shown.get_width() / shown.get_height() - 4 / 3) < 0.02  # its shape kept
assert shown.get_width() == alloc.width or shown.get_height() == alloc.height  # as large as fits
shot("photo-full.png")
pics = os.path.join(os.environ["HOME"], "Фото")
app.set_folder(pics)
questions.clear()
app.viewer_save.clicked()  # saved from the viewer, which stays open
assert questions and questions[-1][0].startswith("Сохранить «фото-") and questions[-1][1] == "Сохранить"
wait(lambda: app.viewer_note.get_text().startswith("сохранено"), what="saved from the viewer")
assert app.stack.get_visible_child_name() == "photo" and len(os.listdir(pics)) == 1
app.viewer.tap.emit("released", 1, 5.0, 5.0)
spin(0.2)
assert app.stack.get_visible_child_name() == "chat" and app.title.get_text() == "Мамочка"
assert not app.viewer_save.get_visible()
frame.tap.emit("released", 1, 5.0, 5.0)
spin(0.1)
app.go_back()  # the back way closes it too
assert app.stack.get_visible_child_name() == "chat" and app.open_chat == mama
psave = saves_of([w for w in holds_of(app.view) if w.msg_id == pic.id][0])
assert len(psave) == 1  # in the photo's corner
psave[0].clicked()
wait(lambda: "фото-%s-1.jpg" % pic.id in os.listdir(pics), what="photo saved from the bubble")
app.on_confirm(False)
assert not bm.load_setting("confirm")
questions.clear()
psave = saves_of([w for w in holds_of(app.view) if w.msg_id == pic.id][0])
os.remove(os.path.join(pics, "фото-%s-1.jpg" % pic.id))
psave[0].clicked()
wait(lambda: "фото-%s-1.jpg" % pic.id in os.listdir(pics), what="saved without asking")
assert questions == []
app.on_confirm(True)
# the real save dialog: the focus on Сохранить, not the name (no keyboard over the list)
focused = []


def look_and_cancel():
    dlg = next((w for w in Gtk.Window.list_toplevels()
                if isinstance(w, Gtk.FileChooserDialog) and w.get_visible()), None)
    if dlg is None:
        return True
    focus = dlg.get_focus()
    focused.append(focus is dlg.get_widget_for_response(Gtk.ResponseType.OK))
    dlg.response(Gtk.ResponseType.CANCEL)
    return False


GLib.timeout_add(500, look_and_cancel)
assert real_ask_save_path(pics, "занято.jpg") is None
assert focused == [True], focused
ok("photo in the window")

# --- media: voice in the bubble, video in the player, a file in the browser -------------------
# (what Media does with them is test_media's; here, that the window hands them over)
m = fake.incoming(mama, "", MAMA, attaches=[audio("https://vd.okcdn.ru/a.ogg"),
                                            video(5, "https://i.oneme.ru/t.jpg"),
                                            file(6, "Документ с очень длинным названием.pdf", 2500000)])
fake.media[(mama, m.id, "video")] = "https://vd.okcdn.ru/v.mp4"
fake.media[(mama, m.id, "file")] = "https://fd.oneme.ru/f.pdf"
app.show_list()
app.open(mama)
wait(lambda: any(w.msg_id == m.id for w in holds_of(app.view)), what="media message")
hold = [w for w in holds_of(app.view) if w.msg_id == m.id][0]
play, vid, doc = [b for b in buttons(hold) if not b.get_style_context().has_class("share")
                  and not b.get_style_context().has_class("save")]
assert len(saves_of(hold)) == 3  # the voice, the video and the file each have one
assert play.state == "play" and vid.get_label() == "▶  Видео 0:42" and doc.get_label().startswith("📄")
assert app.media.agent == fake.agent  # set at login
shot("media.png")
play.clicked()
assert hands.sound.did == [("play", "https://vd.okcdn.ru/a.ogg", fake.agent)] and play.state == "pause"
hands.sound.on_time(3.5)
spin(0.1)
assert "0:03" in [w.get_text() for w in walk(hold) if isinstance(w, Gtk.Label)]
vid.clicked()  # the voice stops for the video
wait(lambda: hands.spawned, what="player")
assert hands.spawned[-1][-1] == "https://vd.okcdn.ru/v.mp4" and hands.sound.did[-1] == ("stop",)
assert play.state == "play"
doc.clicked()  # a file: opened; its save button keeps it
wait(lambda: hands.opened, what="file")
assert hands.opened == ["https://fd.oneme.ru/f.pdf"]
# an audio file plays in the bubble too: its link is asked of MAX first
song = fake.incoming(mama, "", MAMA, attaches=[file(7, "Песня про лето.mp3", 3_200_000)])
fake.media[(mama, song.id, "file")] = "https://fd.oneme.ru/song.mp3"
wait(lambda: any(w.msg_id == song.id for w in holds_of(app.view)), what="audio file message")
shold = [w for w in holds_of(app.view) if w.msg_id == song.id][0]
texts = [w.get_text() for w in walk(shold) if isinstance(w, Gtk.Label)]
assert "🎵  Песня про лето.mp3" in texts and "3.1 МБ" in texts, texts
splay = buttons(shold)[0]
assert len(saves_of(shold)) == 1
assert splay.state == "play" and not any((b.get_label() or "").startswith("📄") for b in buttons(shold))
splay.clicked()
wait(lambda: hands.sound.did[-1][:2] == ("play", "https://fd.oneme.ru/song.mp3"), what="audio file plays")
assert fake.asked("media_url")[-1] == {"chat_id": mama, "msg_id": song.id, "kind": "file"}
assert splay.state == "pause"
hands.sound.on_time(5.0, 200.0)
spin(0.1)
texts = [w.get_text() for w in walk(shold) if isinstance(w, Gtk.Label)]
bar = [w for w in walk(shold) if isinstance(w, Gtk.ProgressBar)][0]
assert "0:05" in texts and 0 < bar.get_fraction() < 0.1
shot("audio-file.png")
splay.clicked()  # pause: no new link asked
assert splay.state == "play" and hands.sound.did[-1] == ("toggle",)
# saving: each photo, voice, video or file by its own button, into the folder set
folder = os.path.join(os.environ["HOME"], "Сохранённое")
app.set_folder(folder)
assert bm.load_text("folder", "") == folder and app.folder_label.get_text() == folder
vsave, video_save, file_save = saves_of(hold)
for b in (vsave, video_save, file_save):
    b.clicked()
    # busy till saved: not to be pressed again, a spinner in the icon's place
    assert not b.get_sensitive() and isinstance(b.get_image(), Gtk.Spinner)
wait(lambda: len(os.listdir(folder)) == 3, what="three saved")
wait(lambda: all(b.get_sensitive() for b in (vsave, video_save, file_save)), what="buttons back")
assert all(isinstance(b.get_image(), Gtk.Image) for b in (vsave, video_save, file_save))
assert sorted(os.listdir(folder)) == sorted(["голосовое-%s.ogg" % m.id, "видео-%s.mp4" % m.id,
                                             "Документ с очень длинным названием.pdf"])
assert {u for u, _h in hands.downloaded} >= {"https://vd.okcdn.ru/a.ogg", "https://vd.okcdn.ru/v.mp4",
                                             "https://fd.oneme.ru/f.pdf"}
wait(lambda: app.sub.get_text() == "сохранено: Документ с очень длинным названием.pdf"
     or app.sub.get_text().startswith("сохранено"), what="said saved")
saves_of(shold)[0].clicked()  # the audio file, by its name
wait(lambda: "Песня про лето.mp3" in os.listdir(folder), what="audio file saved")
hands.fail_download = True
app.sub.set_text("")
app.ask_save_path = lambda where, name: os.path.join(where, name)  # taken: chosen to replace
file_save.clicked()
wait(lambda: app.sub.get_text().startswith("не удалось"), what="save failed")
assert app.sub.get_text() == "не удалось сохранить: 1 из 1" and len(os.listdir(folder)) == 4
hands.fail_download = False
# the name taken: the save dialog, with the folder and the name set
asked = []
app.ask_save_path = lambda where, name: asked.append((where, name)) and None
app.sub.set_text("")
file_save.clicked()  # cancelled: nothing saved, the button free
spin(0.2)
assert asked == [(folder, "Документ с очень длинным названием.pdf")]
assert app.sub.get_text() == "не сохранено" and len(os.listdir(folder)) == 4 and file_save.get_sensitive()
app.ask_save_path = lambda where, name: os.path.join(where, "Копия.pdf")  # another name
file_save.clicked()
wait(lambda: "Копия.pdf" in os.listdir(folder), what="saved under another name")
doc_path = os.path.join(folder, "Документ с очень длинным названием.pdf")
open(doc_path, "w").write("old")
app.ask_save_path = lambda where, name: os.path.join(where, name)  # the same: replaced
file_save.clicked()
wait(lambda: open(doc_path, "rb").read().startswith(b"file from"), what="replaced")
assert len(os.listdir(folder)) == 5 and not [n for n in os.listdir(folder) if "(2)" in n]
# the sound plays only while its chat is in front
def playing_again():
    play.clicked()
    assert play.state == "pause" and app.playing is not None


def stopped():
    return app.playing is None and play.state == "play" and hands.sound.did[-1] == ("stop",)


playing_again()
app.show_forward(mama, m.id)  # within the chat: forwarding, a photo…
assert app.playing is not None
app.end_forward()
app.show_list()  # the chat left
assert stopped()
app.open(mama)
spin(0.2)
playing_again()
app.open(dacha)  # another chat
spin(0.2)
assert stopped()
app.open(mama)
spin(0.2)
playing_again()
app.win.hide()  # the window closed (hidden: MAX lives on in the background)
spin(0.2)
assert stopped()
app.win.show()
spin(0.2)
assert not app.nowplay.get_visible()  # nothing plays: no bar
ok("the sound stops with its chat")

# or, with «Звук играет и вне чата», it plays on and a bar under the header shows it
app.on_keep_sound(True)
assert bm.SETTINGS.get_bool("keep_sound", False)
app.open(mama)
spin(0.2)
playing_again()
assert not app.nowplay.get_visible()  # its chat in front: no bar
app.show_list()
spin(0.2)
assert app.playing is not None and app.nowplay.get_visible()
assert app.nowplay_label.get_text().startswith("🎵  Мамочка  ·  ")
shot("nowplay.png")
app.nowplay_toggle.clicked()  # pause from the bar
assert hands.sound.did[-1] == ("toggle",) and app.nowplay_toggle.state == "play"
assert play.state == "play"
app.nowplay_toggle.clicked()
app.open(dacha)  # another chat: still playing, the bar there too
spin(0.2)
assert app.playing is not None and app.nowplay.get_visible()
back = [w for w in walk(app.nowplay) if isinstance(w, Gtk.Button)][0]
back.clicked()  # a tap on the bar goes back to its chat, at the message playing
spin(0.3)
assert app.open_chat == mama and not app.nowplay.get_visible()
lit = [w for w in holds_of(app.view) if w.get_style_context().has_class("found")]
assert [w.msg_id for w in lit] == [m.id], [w.msg_id for w in lit]


# what plays, as the desktop sees it (MPRIS), from another connection to the bus
from gi.repository import Gio  # noqa: E402
other = Gio.DBusConnection.new_for_address_sync(
    Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION, None),
    Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
    None, None)


def mpris(method, iface, *args, sig=None):
    out = []
    other.call(bm.MPRIS_NAME, bm.MPRIS_PATH, iface, method,
               GLib.Variant(sig, args) if sig else None, None, Gio.DBusCallFlags.NONE, 3000,
               None, lambda c, r: out.append(c.call_finish(r)))
    wait(lambda: out, what="MPRIS " + method)
    return out[0].unpack() if out[0] is not None else None


def prop(name):
    return mpris("Get", "org.freedesktop.DBus.Properties", "org.mpris.MediaPlayer2.Player", name,
                 sig="(ss)")[0]


assert prop("PlaybackStatus") == "Playing"
meta = prop("Metadata")
assert meta["xesam:title"] == "Голосовое сообщение" and meta["xesam:artist"] == ["Мамочка"]
assert mpris("Get", "org.freedesktop.DBus.Properties", "org.mpris.MediaPlayer2", "DesktopEntry",
             sig="(ss)")[0] == bm.APP_ID
mpris("PlayPause", "org.mpris.MediaPlayer2.Player")  # paused from the desktop
assert prop("PlaybackStatus") == "Paused" and play.state == "play"
mpris("Play", "org.mpris.MediaPlayer2.Player")
assert prop("PlaybackStatus") == "Playing" and play.state == "pause"
app.show_list()
spin(0.2)
mpris("Raise", "org.mpris.MediaPlayer2")  # the desktop raises it: at the message
spin(0.3)
assert app.open_chat == mama
app.show_list()
spin(0.2)
mpris("Stop", "org.mpris.MediaPlayer2.Player")
assert prop("PlaybackStatus") == "Stopped" and app.playing is None
assert prop("Metadata")["mpris:trackid"] == "/org/mpris/MediaPlayer2/TrackList/NoTrack"
app.open(mama)
spin(0.2)
playing_again()
app.win.hide()  # the window hidden: it plays on
spin(0.2)
assert app.playing is not None
app.win.show()
app.show_list()
spin(0.2)
app.nowplay_stop.clicked()  # ✕ on the bar
assert stopped() and not app.nowplay.get_visible()
app.on_keep_sound(False)
app.open(mama)
spin(0.2)
ok("the sound plays on, with its bar")
play.clicked()
app.views.pop(mama).destroy()  # the bubble goes (the chat cut or deleted): so does the sound
app.view = None
spin(0.1)
assert hands.sound.did[-1] == ("stop",) and app.playing is None
ok("media")

# --- telemetry: the screens really gone through ----------------------------------------------
screens = [e["params"]["screen_to"] for e in app.telemetry.queue if e["event"] == "GO"]
screens += [e["params"]["screen_to"] for call in fake.asked("log") for e in call["events"]
            if e["event"] == "GO"]
assert {bm.SCREEN_CHATS, bm.SCREEN_CHAT, bm.SCREEN_SEARCH} <= set(screens), screens
ok("telemetry")
