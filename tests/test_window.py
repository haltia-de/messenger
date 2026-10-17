# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2026 Mikhail Nevskiy
"""The window with the real Backend on the fake link (needs a display:
tests/run.sh gives it broadwayd). What is checked is what the window shows
and what was asked of MAX."""
import os
import time

from common import load, ok

bm = load()
from fake_link import FakeLink, audio, file, now_ms, video  # noqa: E402
from gi.repository import GLib, Gtk  # noqa: E402

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


def at_bottom(v):
    adj = v.widget.get_vadjustment()
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
app = bm.Max(link=fake)
buzzes = []
app.buzz = lambda *a: buzzes.append(1) or True
app.register(None)
app.do_activate()
wait(lambda: app.summaries and app.backend.me, what="login")
spin(0.3)

# --- the list: tabs, strangers hidden, channels quiet --------------------------------------
assert rows() == [dacha, mama], rows()  # the stranger's dialog is hidden, channels elsewhere
assert app.tab_channels.get_label() == "Каналы · 4"
app.tab_channels.set_active(True)
spin(0.1)
assert rows() == [news]
app.tab_chats.set_active(True)
spin(0.1)
assert fake.asked("chat_invites") == [{"contacts_only": True}]
shot("list.png")
ok("list")

# --- incoming: buzz from a contact, nothing from a stranger or a channel --------------------
row_before = app.rows[mama]
buzzes.clear()
fake.incoming(spam, "Купите", SPAM)
spin(0.3)
assert not buzzes and spam not in rows()
fake.incoming(news, "Срочно", 50)
spin(0.3)
assert not buzzes
fake.incoming(mama, "Позвони вечером", MAMA)
wait(lambda: buzzes, what="buzz")
assert rows()[0] == mama and app.rows[mama] is row_before  # the row is kept, redrawn
app.on_contacts_only(False)
spin(0.1)
assert spam in rows()
app.on_contacts_only(True)
spin(0.1)
ok("incoming")

# --- pinning and notifications ---------------------------------------------------------------
app.toggle_pin(app.summaries[dacha])
spin(0.1)
assert rows()[0] == dacha and bm.load_json(bm.PREFS, {})["pinned"] == [dacha]
app.toggle_pin(app.summaries[dacha])
app.toggle_mute(app.summaries[news])  # a channel: notifications on
buzzes.clear()
fake.incoming(news, "Новость", 50)
wait(lambda: buzzes, what="channel buzz")
app.toggle_mute(app.summaries[news])
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
app.ask_rename()
app.name_entry.set_text("  Мамочка ")
app.rename()
wait(lambda: app.title.get_text() == "Мамочка", what="rename")
assert app.summaries[mama]["title"] == "Мамочка"
ok("reactions, rename")

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
wait(lambda: olga in app.summaries, what="new dialog")
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
app.trash.clicked()
assert app.confirm_yes.get_label() == "Отписаться"
app.confirm_yes.clicked()
wait(lambda: app.stack.get_visible_child_name() == "chats", what="left")
assert fake.asked("leave")[-1] == {"chat_id": -70} and -70 not in app.summaries
ok("search, join, leave")

# --- a long chat: pages as the reader scrolls up, a spinner, cut on leaving -------------------
big = fake.group(-50, "Большая", members=[PETYA])
tb = now_ms() - 10 * 86400000
for i in range(200):
    fake.say(big, "сообщение %d" % i, PETYA, t=tb + i * 600000)  # ten-minute steps: two days
fake.incoming(big, "последнее", PETYA)
wait(lambda: big in app.summaries, what="big chat")
bm.PREFETCH = 0  # only the reader's scrolling fetches here
app.open(big)
wait(lambda: len(holds_of(app.view)) >= bm.PAGE, what="first page")
v = app.view
assert at_bottom(v)
spinner_seen = False
for _ in range(15):
    v.widget.get_vadjustment().set_value(0)
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
adj = v.widget.get_vadjustment()
adj.set_value(adj.get_upper() / 3)
spin(0.2)
place = adj.get_value()
app.show_list()
app.open(big)
spin(0.5)
assert abs(adj.get_value() - place) < 5, (adj.get_value(), place)
fake.incoming(big, "чужое", PETYA)
spin(0.5)
assert abs(adj.get_value() - place) < 5
app.entry.set_text("своё")
app.send()
wait(lambda: at_bottom(v), what="own message at the bottom")
ok("scroll rules")

# --- media: voice in the bubble, video in the player, a file in the browser -------------------
launched, uris = [], []
bm.subprocess.Popen = lambda cmd, **kw: launched.append(cmd)
Gtk.show_uri_on_window = lambda w, u, t: uris.append(u)
m = fake.incoming(mama, "", MAMA, attaches=[audio("https://vd.okcdn.ru/a.ogg"),
                                            video(5, "https://i.oneme.ru/t.jpg"),
                                            file(6, "Документ с очень длинным названием.pdf", 2500000)])
fake.media[(mama, m.id, "video")] = "https://vd.okcdn.ru/v.mp4"
fake.media[(mama, m.id, "file")] = "https://fd.oneme.ru/f.pdf"
app.show_list()
app.open(mama)
wait(lambda: any(w.msg_id == m.id for w in holds_of(app.view)), what="media message")
hold = [w for w in holds_of(app.view) if w.msg_id == m.id][0]
play, vid, doc = buttons(hold)
assert play.get_label() == "▶" and vid.get_label() == "▶  Видео 0:42" and doc.get_label().startswith("📄")
shot("media.png")
vid.clicked()
wait(lambda: launched, what="player")
assert launched[-1][-2:] == ["--", "https://vd.okcdn.ru/v.mp4"] and "--ytdl=no" in launched[-1]
assert "--user-agent=" + fake.agent in launched[-1]
log = open(bm.PLAYER_LOG).read()
assert "video vd.okcdn.ru/v.mp4 via mpv" in log and oct(os.stat(bm.PLAYER_LOG).st_mode & 0o777) == "0o600"
doc.clicked()
wait(lambda: uris, what="file")
assert uris == ["https://fd.oneme.ru/f.pdf"]


class FakeSound:
    mpv = True

    def __init__(self):
        self.did = []

    def play(self, url):
        self.did.append(("play", url))

    def stop(self):
        self.did.append(("stop",))

    def toggle(self):
        return True


app.sound = FakeSound()
play.clicked()
assert app.sound.did == [("play", "https://vd.okcdn.ru/a.ogg")] and play.get_label() == "⏸"
app.views.pop(mama).destroy()  # the bubble goes (the chat cut or deleted): so does the sound
app.view = None
spin(0.1)
assert app.sound.did[-1] == ("stop",) and app.playing is None
ok("media")

# --- telemetry: the screens really gone through ----------------------------------------------
screens = [e["params"]["screen_to"] for e in app.telemetry.queue if e["event"] == "GO"]
screens += [e["params"]["screen_to"] for call in fake.asked("log") for e in call["events"]
            if e["event"] == "GO"]
assert {bm.SCREEN_CHATS, bm.SCREEN_CHAT, bm.SCREEN_SEARCH} <= set(screens), screens
ok("telemetry")
