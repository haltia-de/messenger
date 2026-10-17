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
assert bm.media_ok("https://vd.okcdn.ru/v.mp4") and bm.media_ok("https://i.oneme.ru/f")
assert bm.media_ok("https://x.mycdn.me/v") and not bm.media_ok("http://i.oneme.ru/a")
for bad in ("https://192.168.1.1/a", "https://localhost/a", "file:///etc/passwd",
            "https://127.0.0.1/", "https://0x7f000001/a", "https://evil.com/a",
            "https://okcdn.ru.evil.com/a"):
    assert not bm.media_ok(bad), bad
assert bm.photo_ok("https://pimg.mycdn.me/t.jpg") and not bm.photo_ok("https://evil.com/t.jpg")
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
assert said(ui, "logged_in")[-1] == (fake.me.id, 7) and bm.AGENT == fake.agent
assert fake.asked("chat_invites") == [{"contacts_only": True}]  # the default, once
run(B.on_login(fake.me, [], [], fake.agent, 7))
assert len(fake.asked("chat_invites")) == 1  # not again at the next login
# a stranger's new dialog later is not known
spam = fake.dialog(SPAM)
fake.say(spam, "акция", SPAM)
B2 = bm.Backend(UI(), fake)
assert B2.seeded
run(B2.on_login(fake.me, list(fake.rooms.values()), [], fake.agent, 7))
assert B2.summary(fake.rooms[spam])["stranger"] and not B2.summary(fake.rooms[anna])["stranger"]
B2.remember(SPAM)
assert not B2.summary(fake.rooms[spam])["stranger"] and SPAM in bm.load_json(bm.KNOWN, [])
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
back(B.set_invites(False))
assert fake.asked("chat_invites")[-1] == {"contacts_only": False}
ok("search, join, remove, rename, invites")

# --- the photo cache is pruned by use ---------------------------------------------------
os.makedirs(bm.CHATS, exist_ok=True)
old = os.path.join(bm.PHOTOS, "a.img")
open(old, "w").close()
os.utime(old, (0, 0))
bm.prune_photos()
assert not os.path.exists(old) and os.path.isdir(bm.CHATS)
ok("photo pruning")
