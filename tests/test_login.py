# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2026 Mikhail Nevskiy
"""The messengers' sign-in in the window, on the fake link: the first start
with no login kept (the login page, a QR code in MAX's card), the cards in
the settings, a messenger switched off and on, the logout, a closed keyring."""
import os
import time

from common import load, ok

bm = load()
from fake_link import FakeLink, now_ms  # noqa: E402
from gi.repository import GLib, Gtk  # noqa: E402


def spin(sec=0.0):
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


SHOTS = os.environ.get("HALTIA_SHOTS")


def shot(name):
    if not SHOTS:
        return
    import cairo
    spin(0.4)
    alloc = app.win.get_allocation()
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, alloc.width, alloc.height)
    app.win.draw(cairo.Context(surf))
    surf.write_to_png(os.path.join(SHOTS, name))


def card(box, name="max"):
    return [c for c in box.get_children() if c.account == name][0]


def buttons(c):
    return {b.get_label(): b for b in c.get_children() if isinstance(b, Gtk.Button)}


def switch(c):
    return [w for w in c.get_children()[0].get_children() if isinstance(w, Gtk.Switch)][0]


fake = FakeLink()
fake.kept = False  # the first start: no login yet
MAMA = 10
fake.person(MAMA, "Мама", contact=True)
mama = fake.dialog(MAMA)
fake.say(mama, "Привет", MAMA, t=now_ms())
bm.save_json(bm.KNOWN, [MAMA])
tg = FakeLink(me="tg:1", name="Я", account="telegram", label="Telegram", prefix="tg:",
              can={"phone", "links", "search", "react", "forward"}, hosts=("t.me",))
tg.kept = False
tg.password = "секрет"  # Telegram's two-step verification
SASHA = tg.person("tg:77", "Внук Саша", contact=True)
sasha = tg.dialog(SASHA)
tg.say(sasha, "Привет из Telegram", SASHA, t=now_ms())
app = bm.Max(link=[fake, tg])
asked = []
bm.dialogs.ask = lambda parent, question, yes, *a: asked.append(question) or True
app.set_flags(app.get_flags() | bm.Gio.ApplicationFlags.NON_UNIQUE)  # beside a running one
app.register(None)
app.do_activate()

# --- the first start: the login page, MAX's card asks to sign in -----------------------------
wait(lambda: app.stack.get_visible_child_name() == "login", what="the login page")
c = card(app.login_cards)
assert c.state == "out" and fake.runs == 0  # nothing started without the person
assert card(app.settings_cards).state == "out"  # the settings draw the same
shot("login.png")
buttons(c)["Войти по QR-коду"].clicked()
wait(lambda: card(app.login_cards).state == "waiting", what="the QR code")
assert any(isinstance(w, Gtk.Image) for w in card(app.login_cards).get_children())
assert fake.runs == 1
fake.scan()
wait(lambda: app.stack.get_visible_child_name() == "chats", what="the list")
wait(lambda: card(app.settings_cards).state == "in")
c = card(app.settings_cards)
assert any(isinstance(w, Gtk.Label) and w.get_text() == "Вход выполнен: Я" for w in c.get_children())
assert mama in app.chatlist.chats
app.show_settings()
shot("settings-accounts.png")
ok("first start: a QR code in the card, then the list")

# --- switched off and on: disconnected, its chats gone, the login kept ------------------------
app.show_settings()
switch(card(app.settings_cards)).set_active(False)
wait(lambda: not app.backend.accounts["max"].online and mama not in app.chatlist.chats,
     what="switched off")
assert card(app.settings_cards).state == "off" and not app.offline.get_visible()
assert bm.SETTINGS.get_bool("account_max", True) is False and fake.kept
switch(card(app.settings_cards)).set_active(True)
wait(lambda: app.backend.accounts["max"].online and mama in app.chatlist.chats, what="on again")
assert fake.runs == 2 and card(app.settings_cards).state == "in"
ok("a messenger switched off and on")

# --- the logout: asked first, then the login and its chats gone ---------------------------------
buttons(card(app.settings_cards))["Выйти"].clicked()
wait(lambda: card(app.settings_cards).state == "out", what="logged out")
assert asked and "Выйти из MAX" in asked[-1] and fake.asked("logout") and not fake.kept
assert mama not in app.chatlist.chats and app.backend.cache.read(mama) == []
ok("the logout")

# --- a closed keyring: said in the card, asked again by «Открыть» ---------------------------------
fake.kept = True
fake.refuse = bm.Locked()
buttons(card(app.settings_cards))["Войти по QR-коду"].clicked()
wait(lambda: card(app.settings_cards).state == "locked", what="the keyring closed")
fake.refuse = None
buttons(card(app.settings_cards))["Открыть"].clicked()
wait(lambda: card(app.settings_cards).state == "in", what="in after unlocking")
ok("a closed keyring")

# --- Telegram: switched on, its QR code, the cloud password; the rows say whose -----------------


def hints(c):
    return [w.get_text() for w in c.get_children() if isinstance(w, Gtk.Label)]


def row_time(chat):
    box = app.rows[chat].get_child()
    right = box.get_children()[-1]
    return right.get_children()[0].get_text()


c = card(app.settings_cards, "telegram")
assert c.state == "off" and not app.tagged and not row_time(mama).startswith("MAX")
switch(c).set_active(True)
wait(lambda: card(app.settings_cards, "telegram").state == "out", what="Telegram signed out")
assert app.tagged and row_time(mama).startswith("MAX · ")  # two messengers: each row says whose
buttons(card(app.settings_cards, "telegram"))["Войти по QR-коду"].clicked()
wait(lambda: card(app.settings_cards, "telegram").state == "waiting", what="Telegram's QR code")
assert any("Подключить устройство" in h for h in hints(card(app.settings_cards, "telegram")))
tg.scan()
wait(lambda: card(app.settings_cards, "telegram").state == "password", what="the password asked")
shot("telegram-password.png")


def give(text):
    entry = [w for w in card(app.settings_cards, "telegram").get_children() if isinstance(w, Gtk.Entry)][0]
    assert not entry.get_visibility()  # dots
    entry.set_text(text)
    entry.activate()


give("не тот")
wait(lambda: any("не подошёл" in h for h in hints(card(app.settings_cards, "telegram"))),
     what="a wrong password said")
give("секрет")
wait(lambda: card(app.settings_cards, "telegram").state == "in", what="in Telegram")
assert "Вход выполнен: Я" in hints(card(app.settings_cards, "telegram"))
wait(lambda: sasha in app.rows, what="Telegram's chat in the list")
assert row_time(sasha).startswith("Telegram · ") and mama in app.rows
switch(card(app.settings_cards, "telegram")).set_active(False)
wait(lambda: sasha not in app.chatlist.chats and not app.tagged, what="Telegram off")
ok("Telegram: the QR code, the cloud password, the rows say whose")
app.quit()
