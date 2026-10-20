# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2026 Mikhail Nevskiy
"""Backend on the fake link, no window: the chat list, known people, the
message cache and its gaps, pages, reactions, invites, renaming, removing;
and the small helpers (phones, links, media hosts, photo pruning)."""
import asyncio
import os

from common import load, ok

bm = load()
from fake_link import FakeLink, audio, file, now_ms, photo, video  # noqa: E402
from gi.repository import GLib  # noqa: E402


class UI:
    """The window's side, as Backend reaches it through GLib.idle_add."""
    def __init__(self):
        self.said = []

    def __getattr__(self, name):
        return lambda *args: self.said.append((name, args)) and False


def drain():
    ctx = GLib.MainContext.default()
    while ctx.iteration(False):
        pass


def said(ui, name):
    drain()
    return [a for n, a in ui.said if n == name]


def run(coro):
    return asyncio.run(coro)


# --- the small helpers ---------------------------------------------------------
assert bm.phone_of("+7 (900) 123-45-67") == "+79001234567"
assert bm.phone_of("89001234567") == bm.phone_of("9001234567") == "+79001234567"
assert bm.phone_of("123") is None and bm.phone_of("Мама") is None
assert bm.link_of("@news") == "https://max.ru/news"
assert bm.link_of("max.ru/join/AbC-d_1") == "https://max.ru/join/AbC-d_1"
assert bm.link_of("https://web.max.ru/rbc/") == "https://max.ru/rbc"
assert bm.link_of("https://evil.com/max.ru/x") is None
ok("helpers")

# --- login: the chat list, names, known people ------------------------------------
fake = FakeLink()
ANNA, PETYA, SPAM = 10, 20, 30
fake.person(ANNA, "Анна Петрова", contact=True)
fake.person(PETYA, "Петя")
fake.person(SPAM, "Спамер")
anna = fake.dialog(ANNA)
petya = fake.dialog(PETYA)
fake.say(anna, "Привет", ANNA)
fake.say(petya, "Как дела?", PETYA)
ui = UI()
B = bm.Backend(ui, fake)
assert not B.seeded
run(B.on_login(fake.me, list(fake.rooms.values()), [fake.people[ANNA]], fake.agent, 7))
summaries = {s["id"]: s for s in said(ui, "show_chats")[-1][0]}
assert summaries[anna]["title"] == "Анна Петрова" and summaries[petya]["title"] == "Петя"
assert B.known == {ANNA, PETYA}  # the first time: everyone already in a dialog
assert oct(os.stat(bm.KNOWN).st_mode & 0o777) == "0o600"
assert said(ui, "logged_in")[-1] == (fake.me.id, 7) and B.agent == fake.agent
assert said(ui, "show_invites")[-1] == ("CONTACTS",)  # MAX's own setting, as it said
# a stranger's new dialog later is not known
spam = fake.dialog(SPAM)
fake.say(spam, "акция", SPAM)
B2 = bm.Backend(UI(), fake)
assert B2.seeded
run(B2.on_login(fake.me, list(fake.rooms.values()), [], fake.agent, 7))
assert B2.summary(fake.rooms[spam])["stranger"] and not B2.summary(fake.rooms[anna])["stranger"]
B2.remember(SPAM)
assert not B2.summary(fake.rooms[spam])["stranger"] and SPAM in bm.load_json(bm.KNOWN, [])
# the login's QR code, drawn without Pillow: a quiet border, then a finder's dark corner
qr = os.path.join(os.environ["HOME"], "qr.png")
bm.qr_png("https://max.ru/:login/abc", qr)
pix = bm.GdkPixbuf.Pixbuf.new_from_file(qr)
px = pix.get_pixels()
side, stride = pix.get_width(), pix.get_rowstride()
assert side == pix.get_height() and side % 12 == 0 and side >= 25 * 12, side


def dark(x, y):
    return px[y * stride + x * pix.get_n_channels()] == 0


assert not dark(5, 5) and dark(2 * 12 + 5, 2 * 12 + 5) and not dark(side - 5, side - 5)
ok("login")

# --- history: no request when nothing is new, gaps, older pages ---------------------
big = fake.group(-50, "Большая", members=[PETYA])
t0 = now_ms() - 10 ** 8
for i in range(100):
    fake.say(big, "m%d" % i, PETYA, t=t0 + i * 1000)
B = bm.Backend(UI(), fake)
run(B.on_login(fake.me, list(fake.rooms.values()), [], fake.agent, 7))
msgs, gap = run(B.history(big))
assert [m["text"] for m in msgs] == ["m%d" % i for i in range(70, 100)] and not gap
assert fake.asked("read")[-1] == {"chat_id": big, "msg_id": fake.msgs[big][-1].id}
n = len(fake.asked("history"))
assert run(B.history(big)) == ([], False) and len(fake.asked("history")) == n  # cached, nothing new
for i in range(40):  # more than a page came meanwhile
    fake.say(big, "n%d" % i, PETYA, t=t0 + 200000 + i * 1000)
fake.rooms[big].new_messages = 40
msgs, gap = run(B.history(big))
assert gap and [m["text"] for m in bm.cache_read(big)] == ["n%d" % i for i in range(10, 40)]
older = run(B.older(big, msgs[0]["time"]))
assert [m["text"] for m in older] == ["m%d" % i for i in range(80, 100)] + \
    ["n%d" % i for i in range(10)]
assert fake.asked("history")[-1] == {"chat_id": big, "backward": bm.PAGE, "before": msgs[0]["time"]}
ok("history")

# --- messages, reactions, media links ------------------------------------------------
# events need the loop: run Backend as the program does
ui = UI()
B = bm.Backend(ui, fake)
B.start()
while B.loop is None or not said(ui, "show_chats"):
    drain()
fake.incoming(anna, "Позвони вечером", ANNA)
while not said(ui, "incoming"):
    drain()
out, summary = said(ui, "incoming")[-1]
assert out["text"] == "Позвони вечером" and out["who"] == "Анна Петрова" and not out["mine"]
assert summary["last"] == "Позвони вечером"
# MAX's own messages come as keys: in words, an unknown one never as the key
fake.incoming(anna, "welcome.saved.dialog.message", None)
while len(said(ui, "incoming")) < 2:
    drain()
out, summary = said(ui, "incoming")[-1]
assert out["text"].startswith("Это Избранное") and summary["last"].startswith("Вы: Это Избранное")
assert B.message(fake.say(anna, "some.new.service.key"))["text"] == "Служебное сообщение"
assert B.message(fake.say(anna, "mail.yandex.ru"))["text"] == "mail.yandex.ru"
m = fake.say(anna, "", ANNA, attaches=[audio("https://vd.okcdn.ru/a.ogg"), video(5, "https://i.oneme.ru/t.jpg"),
                                       file(6, "a.pdf", 2048), photo("https://i.oneme.ru/p.jpg")],
             reactions=[("👍", 2)])
d = B.message(m)
assert [x["kind"] for x in d["media"]] == ["audio", "video", "file"] and d["photos"] == ["https://i.oneme.ru/p.jpg"]
assert d["reactions"] == [["👍", 2]] and d["yours"] is None


def back(coro):
    return asyncio.run_coroutine_threadsafe(coro, B.loop).result(5)


assert back(B.react(anna, m.id, "❤️")) == ([["👍", 2], ["❤️", 1]], "❤️")
fake.counts = False
assert back(B.react(anna, m.id, None)) is None  # no counts from MAX: the window counts
fake.media[(anna, m.id, "video")] = "https://vd.okcdn.ru/v.mp4"
assert back(B.media_url(anna, m.id, {"kind": "video", "id": 5})) == "https://vd.okcdn.ru/v.mp4"
fake.reaction(anna, m.id, [("😂", 1)])
while not said(ui, "reacted"):
    drain()
assert said(ui, "reacted")[-1] == (anna, m.id, [["😂", 1]], ...)
ok("messages, reactions")

# --- forwarding: the new message carries the original, and says from whom -------------------
src = fake.say(anna, "Смотри", ANNA, attaches=[file(8, "план.pdf", 100)])
out, summary = back(B.forward(petya, src.id, anna))
assert out["text"] == "Смотри" and out["media"][0]["name"] == "план.pdf" and out["mine"]
assert out["forwarded"] == "Анна Петрова"  # a dialog has no name: the sender's
assert summary["last"] == "Вы: ↪ Смотри" and [m["id"] for m in bm.cache_read(petya)][-1] == out["id"]
fake.group(-80, "Работа", members=[PETYA])
fake.say(-80, "Собрание", PETYA)
src = fake.msgs[-80][-1]
out, _ = back(B.forward(anna, src.id, -80))
assert out["forwarded"] == "Работа"  # from a group: its name
# what PyMaxLink sends for it: the original's id a number (MAX refuses a string)
pl = bm.forward_payload(-80, "117455094100479781", 11, -1792000000000)
assert pl["message"]["link"] == {"type": "FORWARD", "messageId": 117455094100479781, "chatId": 11}
assert pl["chatId"] == -80 and pl["message"]["cid"] == -1792000000000
import json  # noqa: E402
assert '"messageId": 117455094100479781' in json.dumps(pl)
ok("forwarding")

# --- 2.0's rename: b8k-max's session, data, cache and settings move over once ------------------
import shutil  # noqa: E402
for d in (bm.DATA, bm.PHOTOS, bm.CONFIG):
    shutil.rmtree(d, ignore_errors=True)
OLD_DATA = os.path.join(bm.BASES[1], "b8k-max")
OLD_CACHE = os.path.join(bm.BASES[2], "b8k-max")
os.makedirs(OLD_DATA)
os.makedirs(os.path.join(OLD_CACHE, "chats"))
os.makedirs(os.path.dirname(bm.OLD_CONF))
with open(os.path.join(OLD_DATA, "web.db"), "w") as fh:
    fh.write("session")
os.chmod(os.path.join(OLD_DATA, "web.db"), 0o600)
with open(os.path.join(OLD_CACHE, "chats", "5.json"), "w") as fh:
    fh.write("[]")
with open(bm.OLD_CONF, "w") as fh:
    fh.write("[max]\ntelemetry = no\nfolder = /home/x/Загрузки/MAX\n")
bm.move_old_home()
assert open(os.path.join(bm.DATA, "web.db")).read() == "session"
assert os.stat(os.path.join(bm.DATA, "web.db")).st_mode & 0o777 == 0o600
assert os.path.exists(os.path.join(bm.PHOTOS, "chats", "5.json"))
assert os.path.islink(OLD_DATA) and os.path.islink(OLD_CACHE)  # the kit leaves links, till 3.0
assert os.path.realpath(OLD_DATA) == os.path.realpath(bm.DATA) and not os.path.exists(bm.OLD_CONF)
assert bm.SETTINGS.get_bool("telemetry", True) is False
assert bm.SETTINGS.get("folder") == "/home/x/Загрузки/MAX"
bm.move_old_home()  # once moved, nothing more happens
assert open(os.path.join(bm.DATA, "web.db")).read() == "session"
os.remove(OLD_DATA)
os.remove(OLD_CACHE)
# max.conf moved to ~/.config/haltia by the kit (another program's Settings("max")) first
os.remove(os.path.join(bm.CONFIG, "messenger.conf"))
with open(bm.KIT_CONF, "w") as fh:
    fh.write("[max]\ntelemetry = no\nconfirm = no\n")
bm.move_old_home()
assert bm.SETTINGS.get_bool("telemetry", True) is False and bm.SETTINGS.get_bool("confirm", True) is False
assert os.path.exists(bm.KIT_CONF)  # left for whoever moved it
with open(bm.KIT_CONF, "w") as fh:  # once converted, never again
    fh.write("[max]\ntelemetry = yes\n")
bm.move_old_home()
assert bm.SETTINGS.get_bool("telemetry", True) is False
os.remove(bm.KIT_CONF)
bm.SETTINGS.set("telemetry", True)
bm.SETTINGS.set("confirm", True)
ok("the old home moved")

# --- deletions: MAX's frames read by the link, then the cache and the list ---------------------
from types import SimpleNamespace  # noqa: E402
from pymax.protocol import Opcode  # noqa: E402
got = []


class Events:
    async def on_delete(self, chat_id, ids):
        got.append((chat_id, ids))


async def peek_all():
    link = bm.PyMaxLink("/nonexistent")
    link.events = Events()
    link._peek(SimpleNamespace(opcode=Opcode.NOTIF_MSG_DELETE,
                               payload={"chatId": 11, "messageIds": ["5", 6]}))
    link._peek(SimpleNamespace(opcode=Opcode.NOTIF_MESSAGE, payload={
        "chatId": 12, "message": {"id": 7, "time": 1, "type": "USER", "status": "REMOVED",
                                  "sender": 3, "text": ""}}))
    link._peek(SimpleNamespace(opcode=Opcode.NOTIF_MESSAGE, payload={
        "chatId": 12, "message": {"id": 8, "time": 1, "type": "USER", "sender": 3, "text": "hi"}}))
    link._peek(SimpleNamespace(opcode=Opcode.NOTIF_MSG_DELETE, payload="odd"))
    await asyncio.sleep(0.05)
asyncio.run(peek_all())
assert got == [(11, [5, 6]), (12, [7])], got
seen = []


class Dispatcher:
    async def dispatch(self, frame):
        seen.append(frame)


async def watched():
    link = bm.PyMaxLink("/nonexistent")
    link.events = Events()
    client = SimpleNamespace(_app=SimpleNamespace(dispatcher=Dispatcher()))
    link._watch_deletions(client)
    link._watch_deletions(client)  # a reconnect: not wrapped twice
    frame = SimpleNamespace(opcode=Opcode.NOTIF_MSG_DELETE, payload={"chatId": 21, "messageIds": [9]})
    await client._app.dispatcher.dispatch(frame)
    await asyncio.sleep(0.05)
    assert seen == [frame]  # PyMax still gets every frame, once
got.clear()
asyncio.run(watched())
assert got == [(21, [9])], got
bm.PyMaxLink("/nonexistent")._watch_deletions(SimpleNamespace())  # no runtime yet: nothing
ui_del = UI()
Bd = bm.Backend(ui_del, fake)
run(Bd.on_login(fake.me, list(fake.rooms.values()), [], fake.agent, 7))
k1 = fake.say(anna, "первое", ANNA)
k2 = fake.say(anna, "лишнее", ANNA)
bm.cache_add(anna, [Bd.message(k1), Bd.message(k2)])
Bd.chats[anna].last_message = k2
fake.msgs[anna] = [m for m in fake.msgs[anna] if m.id != k2.id]  # deleted for all in MAX
run(Bd.on_delete(anna, [k2.id]))
assert k2.id not in [m["id"] for m in bm.cache_read(anna)] and k1.id in [m["id"] for m in bm.cache_read(anna)]
chat_id, ids, summary = said(ui_del, "deleted")[-1]
assert chat_id == anna and ids == [k2.id] and summary["last"] == "первое"
ok("deletions")

# --- search, contacts, joining, removing, renaming, invites ----------------------------
fake.person(40, "Ольга", phone="+79001234567")
p = back(B.find_phone("+79001234567"))
assert p == {"id": 40, "name": "Ольга", "chat": fake.me.id ^ 40}
back(B.add_contact(40))
assert 40 in fake.contacts and 40 in B.known
out = back(B.send(fake.me.id ^ 40, "Здравствуйте"))
assert out["mine"] and out["text"] == "Здравствуйте" and fake.me.id ^ 40 in fake.rooms
fake.group(-70, "Новости", kind="CHANNEL", joined=False, link="https://max.ru/news")
info = back(B.link_info("https://max.ru/news"))
assert info["title"] == "Новости" and info["type"] == "CHANNEL" and not info["joined"]
assert back(B.join("https://max.ru/news"))["id"] == -70 and -70 in fake.rooms
back(B.remove(-70))
assert fake.asked("leave")[-1] == {"chat_id": -70} and fake.asked("delete")[-1] == {"chat_id": -70}
back(B.remove(petya))
assert fake.asked("delete")[-1] == {"chat_id": petya} and petya not in B.chats
renamed = back(B.rename(ANNA, "Аня"))
assert [s["title"] for s in renamed] == ["Аня"] and bm.load_json(bm.ALIASES, {}) == {str(ANNA): "Аня"}
back(B.rename(ANNA, ""))
assert B.title(fake.rooms[anna]) == "Анна Петрова"
ok("search, join, remove, rename, invites")

# --- the real link up to PyMax's start, and the settings of the login answer ---------------
import pymax  # noqa: E402
from pymax.api.auth import service as auth  # noqa: E402
from pymax.types.domain.login import LoginResponse  # noqa: E402


class Started(Exception):
    pass


async def stop_at_start(_self):
    raise Started  # all set up before PyMax's runtime exists


real_start = pymax.WebClient.start
pymax.WebClient.start = stop_at_start
link = bm.PyMaxLink(bm.DATA)
try:
    run(link.run(UI()))
    raise AssertionError("start() not reached")
except Started:
    pass
finally:
    pymax.WebClient.start = real_start
assert link.invites() is None  # nothing said yet


class Answer:
    payload = {"config": {"hash": "h", "user": {"CHATS_INVITE": "ALL", "SAFE_MODE": True}}}


assert isinstance(auth.require_payload_model(Answer(), LoginResponse), LoginResponse)
assert link.invites() == "ALL"
link._watch_login()  # a second run does not wrap twice
assert auth.require_payload_model.haltia_real.__module__ == "pymax.api.response"
ok("the link's start and login settings")

# --- the connection: lost, given up, started again; every request answered ------------------
import time  # noqa: E402


def until(cond, secs=5):
    end = time.monotonic() + secs
    while not cond():
        assert time.monotonic() < end, "waited in vain"
        drain()
        time.sleep(0.01)


bm.RETRY = (0.05, 0.05)
fake = FakeLink()
PETR = 40
fake.person(PETR, "Пётр", contact=True)
pc = fake.dialog(PETR)
fake.say(pc, "Привет", PETR)
ui = UI()
B = bm.Backend(ui, fake)
got = []
B.run(B.send(pc, "раньше"), lambda res, err: got.append(err))  # no loop yet: answered all the same
until(lambda: got)
assert isinstance(got[0], bm.Offline)
B.start()
until(lambda: said(ui, "show_chats"))
assert said(ui, "connected") == [(True,)] and B.online
fake.drop()  # the Wi-Fi sleeps; PyMax connects again by itself
until(lambda: said(ui, "connected")[-1] == (False,))
got = []
B.run(B.send(pc, "без связи"), lambda res, err: got.append(err))
until(lambda: got)
assert isinstance(got[0], bm.Offline) and not fake.asked("send")  # not sent at all
fake.back()
until(lambda: said(ui, "connected")[-1] == (True,))
got = []
B.run(B.send(pc, "снова"), lambda res, err: got.append((res, err)))
until(lambda: got)
assert got[0][1] is None and got[0][0]["text"] == "снова"
fake.give_up()  # PyMax gave up: started again after a pause
until(lambda: said(ui, "failed"))
why, pause = said(ui, "failed")[0]
assert "gave up" in why and pause == 0.05 and "link gave up" in open(bm.LOG).read()
until(lambda: fake.runs == 2 and B.online)
bm.RETRY = (30,)
B.tries = 0
fake.give_up()
until(lambda: len(said(ui, "failed")) == 2)
B.retry()  # the wait page's button: not 30 s
until(lambda: fake.runs == 3 and B.online)


class Gone:
    gone = True  # a ChatView destroyed meanwhile


got = []
B.run(B.read(pc, 1), lambda res, err: got.append("gone"), owner=Gone())
B.run(B.read(pc, 1), lambda res, err: got.append("here"))
until(lambda: got)
drain()
assert got == ["here"]
ok("the connection lost, given up and started again; requests always answered")
