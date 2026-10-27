# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mikhail Nevskiy
"""Backend on the fake link, no window: the chat list, known people, the
message cache and its gaps, pages, reactions, invites, renaming, removing;
and the small helpers (phones, links, media hosts, photo pruning)."""
import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import threading

from common import load, ok

bm = load()
from fake_link import FakeLink, audio, file, now_ms, photo, sticker, video  # noqa: E402
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
assert bm.link_of("t.me/club") == "https://t.me/club" and bm.link_of("https://t.me/+AbC_1") == "https://t.me/+AbC_1"
assert bm.link_of("https://evil.com/t.me/x") is None
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
assert not B.accounts["max"].seeded
run(B.accounts["max"].on_login(fake.me, list(fake.rooms.values()), [fake.people[ANNA]], fake.agent, 7))
summaries = {s["id"]: s for s in said(ui, "show_chats")[-1][1]}
assert summaries[anna]["title"] == "Анна Петрова" and summaries[petya]["title"] == "Петя"
assert B.accounts["max"].known == {ANNA, PETYA}  # the first time: everyone already in a dialog
assert oct(os.stat(bm.KNOWN).st_mode & 0o777) == "0o600"
assert said(ui, "logged_in")[-1] == ("max", fake.me.id, 7) and B.accounts["max"].agent == fake.agent
assert said(ui, "show_invites")[-1] == ("CONTACTS",)  # MAX's own setting, as it said
# a stranger's new dialog later is not known
spam = fake.dialog(SPAM)
fake.say(spam, "акция", SPAM)
B2 = bm.Backend(UI(), fake)
assert B2.accounts["max"].seeded
run(B2.accounts["max"].on_login(fake.me, list(fake.rooms.values()), [], fake.agent, 7))
assert B2.accounts["max"].summary(fake.rooms[spam])["stranger"] and not B2.accounts["max"].summary(fake.rooms[anna])["stranger"]
B2.accounts["max"].remember(SPAM)
assert not B2.accounts["max"].summary(fake.rooms[spam])["stranger"] and SPAM in bm.load_json(bm.KNOWN, [])
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
run(B.accounts["max"].on_login(fake.me, list(fake.rooms.values()), [], fake.agent, 7))
msgs, gap = run(B.history(big))
assert [m["text"] for m in msgs] == ["m%d" % i for i in range(70, 100)] and not gap
assert fake.asked("read")[-1] == {"chat_id": big, "msg_id": fake.msgs[big][-1].id}
n = len(fake.asked("history"))
assert run(B.history(big)) == ([], False) and len(fake.asked("history")) == n  # cached, nothing new
for i in range(40):  # more than a page came meanwhile
    fake.say(big, "n%d" % i, PETYA, t=t0 + 200000 + i * 1000)
fake.rooms[big].unread = 40
msgs, gap = run(B.history(big))
assert gap and [m["text"] for m in B.cache.read(big)] == ["n%d" % i for i in range(10, 40)]
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
fake.incoming(anna, "Себе на память", None)  # no sender: the account's own
while len(said(ui, "incoming")) < 2:
    drain()
assert said(ui, "incoming")[-1][1]["last"] == "Вы: Себе на память"
m = fake.say(anna, "", ANNA, attaches=[audio("https://vd.okcdn.ru/a.ogg"), video(5, "https://i.oneme.ru/t.jpg"),
                                       file(6, "a.pdf", 2048), photo("https://i.oneme.ru/p.jpg"),
                                       sticker()],
             reactions=[("👍", 2)])
d = B.accounts["max"].message(m)
assert [x["kind"] for x in d["media"]] == ["audio", "video", "file"] and d["photos"] == ["https://i.oneme.ru/p.jpg"]
assert d["reactions"] == [["👍", 2]] and d["yours"] is None and d["text"] == "[стикер]"
assert B.accounts["max"].preview(m) == "Голосовое сообщение, видео, файл «a.pdf», фото, стикер"


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
assert summary["last"] == "Вы: ↪ Смотри" and [m["id"] for m in B.cache.read(petya)][-1] == out["id"]
fake.group(-80, "Работа", members=[PETYA])
fake.say(-80, "Собрание", PETYA)
src = fake.msgs[-80][-1]
out, _ = back(B.forward(anna, src.id, -80))
assert out["forwarded"] == "Работа"  # from a group: its name
# what PyMaxLink sends for it: the original's id a number (MAX refuses a string)
pl = bm.forward_payload(-80, "117455094100479781", 11, -1792000000000)
assert pl["message"]["link"] == {"type": "FORWARD", "messageId": 117455094100479781, "chatId": 11}
assert pl["chatId"] == -80 and pl["message"]["cid"] == -1792000000000
assert '"messageId": 117455094100479781' in json.dumps(pl)
ok("forwarding")

# --- 2.0's rename: b8k-max's session, data, cache and settings move over once ------------------
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

    async def on_reaction(self, chat_id, msg_id, reactions, yours=...):
        got.append(("reaction", chat_id, msg_id, reactions) + ((yours,) if yours is not ... else ()))


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
    # a reaction as MAX sends it (messageId a number, which PyMax 2.4.1 drops)
    link._peek(SimpleNamespace(opcode=Opcode.NOTIF_MSG_REACTIONS_CHANGED, payload={
        "chatId": 13, "messageId": 117484382192958798, "totalCount": 2,
        "counters": [{"reaction": "❤️", "count": 1}, {"reaction": "👍", "count": 1}]}))
    # the others in the chat get YOU_REACTED, the counts in reactionInfo
    link._peek(SimpleNamespace(opcode=Opcode.NOTIF_MSG_YOU_REACTED, payload={
        "chatId": 13, "messageId": 9, "reactionInfo": {
            "counters": [{"reaction": "👍", "count": 1}], "totalCount": 1, "yourReaction": "👍"}}))
    await asyncio.sleep(0.05)
asyncio.run(peek_all())
assert got == [(11, [5, 6]), (12, [7]),
               ("reaction", 13, 117484382192958798, [["❤️", 1], ["👍", 1]]),
               ("reaction", 13, 9, [["👍", 1]], "👍")], got
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
run(Bd.accounts["max"].on_login(fake.me, list(fake.rooms.values()), [], fake.agent, 7))
k1 = fake.say(anna, "первое", ANNA)
k2 = fake.say(anna, "лишнее", ANNA)
Bd.cache.add(anna, [Bd.accounts["max"].message(k1), Bd.accounts["max"].message(k2)])
Bd.accounts["max"].chats[anna].last = k2
fake.msgs[anna] = [m for m in fake.msgs[anna] if m.id != k2.id]  # deleted for all in MAX
run(Bd.accounts["max"].on_delete(anna, [k2.id]))
assert k2.id not in [m["id"] for m in Bd.cache.read(anna)] and k1.id in [m["id"] for m in Bd.cache.read(anna)]
chat_id, ids, summary = said(ui_del, "deleted")[-1]
assert chat_id == anna and ids == [k2.id] and summary["last"] == "первое"
ok("deletions")

# --- PyMax's objects as the link's own (max_message, max_chat, max_person) -----------------
from pymax.types.domain import Chat as PyChat, Message as PyMessage, User as PyUser  # noqa: E402


def pm(text="", attaches=(), **more):
    return PyMessage.model_validate(dict({"id": 9, "chatId": 11, "sender": 5, "text": text,
                                          "time": 1000, "type": "USER", "attaches": list(attaches)},
                                         **more))


# a call in the history: whose, how it ended, how long
rec = bm.max_message(pm("", [{"_type": "CALL", "conversationId": "c", "callType": "VIDEO",
                              "hangupType": "HUNGUP", "duration": 65000, "contactIds": [5]}]))
assert rec.call == {"video": True, "end": "HUNGUP", "duration": 65000} and not rec.notes
assert bm.call_words(rec.call, False) == ("Входящий видеозвонок", "Принят · 1:05")
for end, ms, mine, how in (("MISSED", 0, False, "Пропущен"), ("MISSED", 0, True, "Без ответа"),
                           ("REJECTED", 0, False, "Отклонён"), ("REJECTED", 0, True, "Отклонён"),
                           ("CANCELED", 0, False, "Пропущен"), ("CANCELED", 0, True, "Отменён"),
                           ("HUNGUP", 24090, True, "Принят · 0:24")):
    assert bm.call_words({"end": end, "duration": ms}, mine)[1] == how, (end, mine)
assert bm.call_words({"end": "HUNGUP", "duration": 1}, True)[0] == "Исходящий звонок"
# an answer carries what it answers: whose, its words
ans = bm.max_message(pm("Да", link={"type": "REPLY", "chatId": 11,
                                    "message": {"id": 3, "sender": 6, "text": "Придёшь?",
                                                "time": 500, "type": "USER"}}))
assert ans.text == "Да" and ans.reply == {"id": 3, "sender": 6, "text": "Придёшь?"} and ans.fwd is None
# MAX's own messages come as keys: in words, an unknown one never as the key
assert bm.max_message(pm("welcome.saved.dialog.message")).text.startswith("Это Избранное")
assert bm.max_message(pm("some.new.service.key")).text == "Служебное сообщение"
assert bm.max_message(pm("mail.yandex.ru")).text == "mail.yandex.ru"
m = bm.max_message(pm("", [
    {"_type": "AUDIO", "url": "https://vd.okcdn.ru/a.ogg", "duration": 7},
    {"_type": "VIDEO", "videoId": 5, "thumbnail": "https://i.oneme.ru/t.jpg", "token": "t",
     "videoType": 0, "width": 640, "height": 360, "duration": 42},
    {"_type": "FILE", "fileId": 6, "name": "a.pdf", "size": 2048, "token": "t"},
    {"_type": "FILE", "fileId": 7, "name": "Песня.MP3", "size": 3000, "token": "t"},
    {"_type": "PHOTO", "baseUrl": "https://i.oneme.ru/p.jpg", "photoId": 1, "width": 640,
     "height": 480, "photoToken": "t"}],
    reactionInfo={"totalCount": 2, "counters": [{"reaction": "👍", "count": 2}],
                  "yourReaction": "👍"}))
assert [x["kind"] for x in m.media] == ["audio", "video", "file", "audio"]
assert m.media[3] == {"kind": "audio", "url": None, "file": 7, "name": "Песня.MP3", "size": 3000,
                      "duration": 0}
assert m.photos == ["https://i.oneme.ru/p.jpg"] and m.notes == []
assert m.parts == ["голосовое сообщение", "видео", "файл «a.pdf»", "файл «Песня.MP3»", ""]
assert m.reactions == [["👍", 2]] and m.yours == "👍" and m.fwd is None
fw = bm.max_message(pm("", link={"type": "FORWARD", "chatId": -80, "chatName": "Работа",
                                 "message": {"id": 3, "sender": 6, "text": "Собрание",
                                             "time": 500, "type": "USER"}}))
assert fw.id == 9 and fw.sender == 5 and fw.text == "Собрание" and fw.fwd == {"chat": "Работа", "sender": 6}
c = bm.max_chat(PyChat.model_validate({
    "id": 11, "type": "DIALOG", "status": "ACTIVE", "owner": 1, "participants": {"1": 0, "5": 0},
    "newMessages": 3, "lastEventTime": 2000,
    "lastMessage": {"id": 9, "sender": 5, "text": "Привет", "time": 1000, "type": "USER"}}))
assert c.kind == "DIALOG" and c.members == [1, 5] and c.count == 2 and c.unread == 3
assert c.title is None and c.time == 2000 and c.last.text == "Привет"
# participants are {id: read mark}: the others' newest is how far they read
read = bm.max_chat(PyChat.model_validate({
    "id": 12, "type": "CHAT", "status": "ACTIVE", "owner": 1,
    "participants": {"1": 9000, "5": 1500, "6": 1700}}), me=1)
assert read.seen == 1700 and bm.max_chat(PyChat.model_validate({
    "id": 12, "type": "CHAT", "status": "ACTIVE", "owner": 1, "participants": {"1": 9000}}), me=1).seen == 0
assert bm.max_person(PyUser.model_validate({"id": 5, "names": [{"name": "Анна", "type": "CUSTOM"}]})) \
    == bm.Person(5, "Анна")
sent_to_max = []


not_ready = [0]  # MAX answers …not.ready this many times first


class Messages:
    async def send_message(self, chat_id, text, attachments=None):
        sent_to_max.append((chat_id, text, attachments))
        if not_ready[0]:
            not_ready[0] -= 1
            from pymax.exceptions import ApiError
            raise ApiError(opcode=64, error="errors.process.attachment.video.not.ready")


link = bm.PyMaxLink("/nonexistent")
link.client = SimpleNamespace(_app=SimpleNamespace(api=SimpleNamespace(
    messages=Messages(), uploads=SimpleNamespace())))
asyncio.run(link.send(11, "", [bm.attachment("/x/Дача.JPG"), bm.attachment("/x/Счёт.pdf"),
                               {"kind": "voice", "path": "/x/v.ogg", "duration": 3200}]))
chat, text, files = sent_to_max[-1]
assert chat == 11 and text is None and [type(f).__name__ for f in files] == ["Photo", "File", "Voice"]
assert files[1].name == "Счёт.pdf" and files[2].duration == 3200
assert link._api.uploads.upload_photo == link._upload_photo  # PyMax 2.4.1's own fail on MAX now
bm.VOICE_PAUSE = 0
not_ready[0] = 2
n = len(sent_to_max)
asyncio.run(link.send(11, "", [{"kind": "voice", "path": "/x/v.ogg", "duration": 3200}]))
assert len(sent_to_max) == n + 3  # not ready twice: sent again, uploaded anew
assert bm.photo_token("https://iu.oneme.ru/uploadImage?r=x", {"photos": {"0": {"token": "T"}}}) == "T"
assert bm.photo_token("https://x/u?photoIds=7", {"photos": {"7": {"token": "A"}, "8": {"token": "B"}}}) == "A"
for bad in ({"photos": {}}, {"photos": {"1": {"token": "A"}, "2": {"token": "B"}}}):
    try:
        bm.photo_token("https://iu.oneme.ru/uploadImage?r=x", bad)
        raise AssertionError("guessed")
    except RuntimeError:
        pass


async def uploads():
    """The uploads against a small server answering as MAX's do."""
    from aiohttp import web
    from pymax.files import Photo, Voice

    got = []

    async def take(request):
        form = await request.post()
        part = form["file"]
        got.append((request.path, part.filename, part.content_type, part.file.read()))
        if request.path == "/bad":
            return web.json_response({"error_code": "1", "error_data": "AUDIO_VALIDATION_FAILED"})
        if request.path == "/uploadImage":
            return web.json_response({"photos": {"0": {"token": "PT"}}})
        return web.Response(text="")

    app = web.Application()
    app.router.add_post("/{name}", take)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    base = "http://127.0.0.1:%d" % site._server.sockets[0].getsockname()[1]
    voice_url = [base + "/uploadAudio"]

    async def invoke(op, payload=None):
        if op.name == "PHOTO_UPLOAD":
            return SimpleNamespace(payload={"url": base + "/uploadImage?r=tok"})
        return SimpleNamespace(payload={"info": [{"url": voice_url[0], "videoId": 55, "token": "VT"}]})

    one = bm.PyMaxLink("/nonexistent")
    one.client = SimpleNamespace(_app=SimpleNamespace(invoke=invoke, config=SimpleNamespace(proxy=None)))
    pic, ogg = os.path.join(bm.PHOTOS, "up.png"), os.path.join(bm.PHOTOS, "up.ogg")
    with open(pic, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n" + b"0" * 16)
    with open(ogg, "wb") as fh:
        fh.write(b"OggS voice")
    try:
        photo = await one._upload_photo(Photo(path=pic))
        voice = await one._upload_voice(Voice(path=ogg, duration=3200))
        voice_url[0] = base + "/bad"
        try:
            await one._upload_voice(Voice(path=ogg, duration=3200))
            raise AssertionError("an error in a 200 taken for a success")
        except RuntimeError as exc:
            assert "AUDIO_VALIDATION_FAILED" in str(exc)
    finally:
        await runner.cleanup()
    return got, photo, voice


asked_max = []


async def public_search(op, payload=None):  # as MAX answered the official client (its log)
    asked_max.append((op.name, payload))
    return SimpleNamespace(payload={"result": [
        {"chat": {"id": -71, "type": "CHANNEL", "title": "«Фонтанка.ру»", "participantsCount": 900,
                  "access": "PUBLIC", "link": "https://max.ru/fontanka", "status": "ACTIVE"},
         "highlights": ["Фонтанка"]},
        {"chat": {"id": -72, "type": "CHAT", "title": "Двор", "link": "https://max.ru/dvor"}},
        {"contact": {"contact": {"id": 9}}}], "total": 3, "marker": 3, "ucpQId": "q"})

finder = bm.PyMaxLink("/nonexistent")
finder.client = SimpleNamespace(_app=SimpleNamespace(invoke=public_search))
found = asyncio.run(finder.search("фонтанка"))
assert asked_max == [("PUBLIC_SEARCH", {"query": "фонтанка", "count": bm.SEARCH_COUNT, "type": "ALL"})]
assert [(c.id, c.kind, c.title, c.count, c.link) for c in found] == [
    (-71, "CHANNEL", "«Фонтанка.ру»", 900, "https://max.ru/fontanka"),
    (-72, "CHAT", "Двор", 0, "https://max.ru/dvor")]  # people left out
got, photo, voice = asyncio.run(uploads())
assert photo.photo_token == "PT" and got[0][0] == "/uploadImage" and got[0][2] == "image/png"
assert got[1][:3] == ("/uploadAudio", "up.ogg", "audio/ogg") and got[1][3] == b"OggS voice"
attach = voice.model_dump(by_alias=True)
assert attach["token"] == "VT" and "audioId" not in attach and attach["duration"] == 3200  # as MAX's app
assert attach["wave"] == bytes(80)  # flat: up.ogg is no real Ogg
frame = json.loads(json.dumps(voice.model_dump(by_alias=True, mode="json")))
assert len(frame["wave"]) == 80  # MAX checks the string's length
tone = os.path.join(bm.PHOTOS, "tone.ogg")
if shutil.which("ffmpeg"):
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=d=2",
                    "-ac", "1", "-c:a", "libopus", tone], check=True)
    levels = bm.voice_wave(tone)
    assert len(levels) == 80 and max(levels) > 0 and max(levels) <= 127
    # every 8th sample gives the levels of every sample, to within noise
    pcm = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", tone, "-ac", "1", "-ar", "8000",
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    every = memoryview(pcm[:len(pcm) // 2 * 2]).cast("h")
    n = len(every)
    full = [min(127, int(sum(abs(x) for x in every[i * n // 80:(i + 1) * n // 80])
                         / max(1, (i + 1) * n // 80 - i * n // 80) / 32768 * 800)) for i in range(80)]
    assert all(abs(a - b) <= 3 for a, b in zip(levels, full)), (list(levels), full)
assert bm.attachment_words([bm.attachment("/x/a.png"), bm.attachment("/x/b.pdf")]) == "Фото, файл «b.pdf»"
ok("PyMax's objects as the link's own")

# --- Telethon's objects as the link's own; the Telegram link on a stand-in client -------------
from datetime import datetime, timezone  # noqa: E402

from telethon.tl import types as tt  # noqa: E402

T0 = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def doc(*attributes, mime="application/octet-stream", thumbs=None):
    return tt.MessageMediaDocument(document=tt.Document(
        id=1, access_hash=2, file_reference=b"", date=T0, mime_type=mime, size=2048, dc_id=2,
        attributes=list(attributes), thumbs=thumbs))


def tmsg(mid=5, peer=tt.PeerUser(77), sender=None, text="", media=None, **kw):
    return tt.Message(id=mid, peer_id=peer, date=T0, message=text, media=media,
                      from_id=sender, **kw)


m = bm.tg_message(tmsg(text="Привет", sender=tt.PeerUser(77), media=tt.MessageMediaPhoto(
    photo=tt.Photo(id=1, access_hash=2, file_reference=b"", date=T0, sizes=[], dc_id=2)),
    reactions=tt.MessageReactions(results=[
        tt.ReactionCount(reaction=tt.ReactionEmoji(emoticon="❤"), count=2, chosen_order=0),
        tt.ReactionCount(reaction=tt.ReactionCustomEmoji(document_id=9), count=1)])))
assert (m.id, m.chat, m.sender, m.text, m.time) == (5, "tg:77", "tg:77", "Привет", 1792497600000)
assert m.photos == ["tg:77/5"] and m.reactions == [["❤️", 2]] and m.yours == "❤️"  # REACTIONS' heart
m = bm.tg_message(tmsg(peer=tt.PeerChannel(5), media=doc(
    tt.DocumentAttributeAudio(duration=7, voice=True), mime="audio/ogg")))
assert m.chat == "tg:-1000000000005" and m.sender == m.chat  # a channel's post: the channel's
assert m.media == [{"kind": "audio", "url": "tg:-1000000000005/5", "duration": 7}]
m = bm.tg_message(tmsg(media=doc(tt.DocumentAttributeVideo(duration=42, w=640, h=480),
                                 mime="video/mp4", thumbs=[tt.PhotoStrippedSize("i", b"x")])))
assert m.media == [{"kind": "video", "id": "tg:77/5", "thumb": "tg:77/5/thumb", "duration": 42}]
m = bm.tg_message(tmsg(media=doc(tt.DocumentAttributeFilename("Счёт.pdf"), mime="application/pdf")))
assert m.media == [{"kind": "file", "id": "tg:77/5", "name": "Счёт.pdf", "size": 2048}]
assert m.parts == ["файл «Счёт.pdf»"]
m = bm.tg_message(tmsg(media=doc(tt.DocumentAttributeAudio(duration=200, title="Песня",
                                                           performer="Хор"), mime="audio/mpeg")))
assert m.media[0]["kind"] == "audio" and m.media[0]["name"] == "Хор — Песня"
m = bm.tg_message(tmsg(text="а это", fwd_from=tt.MessageFwdHeader(date=T0, from_name="Тётя Валя")))
assert m.fwd == {"chat": "Тётя Валя", "sender": None}
m = bm.tg_message(tt.MessageService(id=6, peer_id=tt.PeerChat(9), date=T0,
                                    action=tt.MessageActionPinMessage()))
assert m.chat == "tg:-9" and m.notes == ["закреплено сообщение"]
m = bm.tg_message(tt.MessageService(id=7, peer_id=tt.PeerUser(77), date=T0, action=tt.MessageActionPhoneCall(
    call_id=1, video=True, reason=tt.PhoneCallDiscardReasonHangup(), duration=65)))
assert m.call == {"video": True, "end": "HUNGUP", "duration": 65000} and not m.notes
m = bm.tg_message(tt.MessageService(id=8, peer_id=tt.PeerUser(77), date=T0, action=tt.MessageActionPhoneCall(
    call_id=2, reason=tt.PhoneCallDiscardReasonMissed())))
assert m.call == {"video": False, "end": "MISSED", "duration": 0}
m = bm.tg_message(tmsg(text="Да", reply_to=tt.MessageReplyHeader(reply_to_msg_id=5)))
assert m.reply == {"id": 5, "sender": None, "text": ""}  # its words from the chat, if known
assert bm.tg_message(tmsg(text="моё", out=True), "tg:1").sender == "tg:1"  # Telegram leaves it out
assert bm.tg_person(tt.User(id=77, first_name="Саша", last_name="Иванов")) == bm.Person("tg:77", "Саша Иванов")
c = bm.tg_chat(tt.User(id=77, first_name="Саша"), "tg:1", unread=2, last=tmsg(text="Привет"), seen=41)
assert c.seen == 41  # read_outbox_max_id: own messages up to it are read
assert (c.id, c.kind, c.title, c.members, c.unread, c.last.text) == \
    ("tg:77", "DIALOG", None, ["tg:1", "tg:77"], 2, "Привет")
assert bm.tg_chat(tt.User(id=1, first_name="Я", is_self=True), "tg:1").members == ["tg:1"]
c = bm.tg_chat(tt.Channel(id=5, title="Новости", photo=tt.ChatPhotoEmpty(), date=T0, broadcast=True,
                          participants_count=900), "tg:1")
assert (c.id, c.kind, c.title, c.count) == ("tg:-1000000000005", "CHANNEL", "Новости", 900)
c = bm.tg_chat(tt.Chat(id=9, title="Семья", photo=tt.ChatPhotoEmpty(), participants_count=4,
                       date=T0, version=1), "tg:1")
assert (c.id, c.kind) == ("tg:-9", "CHAT")


class Client:
    """Telethon's client as the link meets it, without Telegram."""
    def __init__(self):
        self.calls = []

    async def get_input_entity(self, n):
        return ("peer", n)

    async def get_messages(self, peer, ids=None, limit=None, offset_date=None):
        self.calls.append(("get_messages", peer, ids, limit, offset_date))
        return tmsg(mid=ids, media=doc(tt.DocumentAttributeFilename("a.pdf"))) if ids else \
            [tmsg(mid=9, text="новое"), tmsg(mid=8, text="старое")]

    async def download_media(self, msg, file, thumb=None):
        self.calls.append(("download_media", msg.id, thumb))
        file.write(b"data")

    async def send_message(self, peer, text):
        self.calls.append(("send_message", peer, text))
        return tmsg(mid=20, text=text, out=True)

    async def send_file(self, peer, path, caption="", **kw):
        self.calls.append(("send_file", os.path.basename(path), caption, sorted(kw)))
        return tmsg(mid=21 + len(self.calls), text=caption, out=True)

    async def __call__(self, request):
        self.calls.append(request)
        return tt.Updates(updates=[tt.UpdateMessageReactions(
            peer=tt.PeerUser(77), msg_id=5, reactions=tt.MessageReactions(results=[
                tt.ReactionCount(reaction=tt.ReactionEmoji(emoticon="🤣"), count=1, chosen_order=0)]))],
            users=[], chats=[], date=T0, seq=0)


link = bm.TelethonLink(bm.DATA)
link.client = cl = Client()
assert (link.account, link.prefix, link.dialog_of("tg:1", "tg:77")) == ("telegram", "tg:", "tg:77")
got = run(link.history("tg:77", 30, before=1792497600000))
assert [m.id for m in got] == [9, 8] and cl.calls[-1][1:4] == (("peer", 77), None, 30)
assert cl.calls[-1][4] == T0
dl = os.path.join(bm.PHOTOS, "tg.part")
os.makedirs(bm.PHOTOS, exist_ok=True)
run(link.download("tg:-1000000000005/12/thumb", dl))
assert open(dl, "rb").read() == b"data" and cl.calls[-2][2] == 12 and cl.calls[-1] == ("download_media", 12, -1)
assert cl.calls[-2][1] == ("peer", -1000000000005)
run(link.download("tg:77/13", dl))
assert cl.calls[-1] == ("download_media", 13, None)
assert run(link.send("tg:77", "Привет")).text == "Привет"
voice = {"kind": "voice", "path": "/x/v.ogg", "duration": 3200}
sent = run(link.send("tg:77", "Вот", [bm.attachment("/x/a.jpg"), bm.attachment("/x/b.pdf"), voice]))
assert [m.text for m in sent] == ["Вот", "", ""]
assert [c[1:3] for c in cl.calls[-3:]] == [("a.jpg", "Вот"), ("b.pdf", ""), ("v.ogg", "")]
assert "force_document" in cl.calls[-2][3] and "voice_note" in cl.calls[-1][3]
assert run(link.react("tg:77", 5, "😂")) == ([["😂", 1]], "😂")  # Telegram's 🤣, as REACTIONS has it
assert cl.calls[-1].reaction[0].emoticon == "🤣"
assert run(link.media_url("tg:77", 5, {"kind": "video", "id": "tg:77/5"})) == "tg:77/5"
# The application's keys: none here, so Telegram cannot be had; [telegram] in the settings gives them.
B0 = bm.Backend(UI())
assert bm.telegram_keys() is None and "api_id" in B0.missing("telegram") and B0.missing("max") is None
with open(bm.SETTINGS.path, "a") as fh:
    fh.write("\n[telegram]\napi_id = 12345\napi_hash = abc\n")
assert bm.telegram_keys() == (12345, "abc") and B0.missing("telegram") is None
ok("Telethon's objects as the link's own; the Telegram link")

# --- search, contacts, joining, removing, renaming, invites ----------------------------
fake.person(40, "Ольга", phone="+79001234567")
[p] = back(B.find_phone("+79001234567"))
assert p == {"id": 40, "name": "Ольга", "account": "max", "label": "MAX", "chat": fake.me.id ^ 40}
back(B.add_contact(40))
assert 40 in fake.contacts and 40 in B.accounts["max"].known
out = back(B.send(fake.me.id ^ 40, "Здравствуйте"))
assert out["mine"] and out["text"] == "Здравствуйте" and fake.me.id ^ 40 in fake.rooms
fake.group(-70, "Новости", kind="CHANNEL", joined=False, link="https://max.ru/news")
info = back(B.link_info("https://max.ru/news"))
assert info["title"] == "Новости" and info["type"] == "CHANNEL" and not info["joined"]
assert back(B.join("https://max.ru/news"))["id"] == -70 and -70 in fake.rooms
back(B.remove(-70))
assert fake.asked("leave")[-1] == {"chat_id": -70} and fake.asked("delete")[-1] == {"chat_id": -70}
back(B.remove(petya))
assert fake.asked("delete")[-1] == {"chat_id": petya} and petya not in B.accounts["max"].chats
renamed = back(B.rename(ANNA, "Аня"))
assert [s["title"] for s in renamed] == ["Аня"] and bm.load_json(bm.ALIASES, {}) == {str(ANNA): "Аня"}
back(B.rename(ANNA, ""))
assert B.accounts["max"].title(fake.rooms[anna]) == "Анна Петрова"
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

# --- the login in the keyring: PyMax's session through the Vault, web.db moved in once -----------
from haltia_kit.testing import FakeKeyring  # noqa: E402
from pymax.session.models import SessionInfo  # noqa: E402
from pymax.session.store import SessionStore  # noqa: E402

ring = FakeKeyring()
vault = bm.Vault(bm.APP_ID, bm.DATA, key="account", file="%s-session.json", keyring=ring)
store = bm.VaultStore(vault, "max")
old_dir = os.path.join(bm.PHOTOS, "old-session")


async def keyring_story():
    old = SessionStore(old_dir, "web.db")
    await old.save_session(SessionInfo(token="T1", device_id="D1", phone=""))
    await old.close()
    await store.take_old(old_dir)
    assert not os.path.exists(os.path.join(old_dir, "web.db"))  # moved in: gone
    info = await store.load_session()
    assert info.token == "T1" and info.device_id == "D1" and "T1" in ring.kept["max"]
    await store.update_token("T1", "T2")
    assert (await store.load_session()).token == "T2"
    assert (await store.load_session_by_device_id("D1")).token == "T2"
    assert await store.load_session_by_phone("+7") is None
    await store.delete_session("T2")
    assert await store.load_session() is None and "max" not in ring.kept
    ring.locked = True  # the person refused to unlock it: said, never a file instead
    try:
        await store.save_session(SessionInfo(token="T3", device_id="D1", phone=""))
        raise AssertionError("not refused")
    except bm.Locked:
        pass
    assert vault.state == "locked" and not os.path.exists(os.path.join(bm.DATA, "max-session.json"))
    ring.locked = False
    await store.save_session(SessionInfo(token="T3", device_id="D1", phone=""))
    assert vault.state == "keyring"
    files = bm.Vault(bm.APP_ID, bm.DATA, key="account", file="%s-session.json", keyring=None)
    await bm.VaultStore(files, "max").save_session(SessionInfo(token="T4", device_id="D", phone=""))
    path = os.path.join(bm.DATA, "max-session.json")  # no Secret Service at all (the tablet): a file
    assert oct(os.stat(path).st_mode & 0o777) == "0o600" and "T4" in open(path).read()
    os.remove(path)
asyncio.run(keyring_story())
ok("the login in the keyring")

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
assert said(ui, "connected") == [("max", True)] and B.accounts["max"].online
fake.drop()  # the Wi-Fi sleeps; PyMax connects again by itself
until(lambda: said(ui, "connected")[-1] == ("max", False))
got = []
B.run(B.send(pc, "без связи"), lambda res, err: got.append(err))
until(lambda: got)
assert isinstance(got[0], bm.Offline) and not fake.asked("send")  # not sent at all
fake.back()
until(lambda: said(ui, "connected")[-1] == ("max", True))
got = []
B.run(B.send(pc, "снова"), lambda res, err: got.append((res, err)))
until(lambda: got)
assert got[0][1] is None and got[0][0]["text"] == "снова"
fake.give_up()  # PyMax gave up: started again after a pause
until(lambda: said(ui, "failed"))
_account, why, pause = said(ui, "failed")[0]
assert "gave up" in why and pause == 0.05 and "link gave up" in open(bm.LOG).read()
until(lambda: fake.runs == 2 and B.accounts["max"].online)
bm.RETRY = (30,)
B.accounts["max"].tries = 0
fake.give_up()
until(lambda: len(said(ui, "failed")) == 2)
B.retry()  # the wait page's button: not 30 s
until(lambda: fake.runs == 3 and B.accounts["max"].online)


class Gone:
    gone = True  # a ChatView destroyed meanwhile


got = []
B.run(B.read(pc, 1), lambda res, err: got.append("gone"), owner=Gone())
B.run(B.read(pc, 1), lambda res, err: got.append("here"))
until(lambda: got)
drain()
assert got == ["here"]
ok("the connection lost, given up and started again; requests always answered")

# --- two messengers: each its own account, requests to whose ids they are --------------------
fake = FakeLink()
fake.person(ANNA, "Анна", contact=True, phone="+79001112233")
anna = fake.dialog(ANNA)
fake.say(anna, "Привет из MAX", ANNA)
tg = FakeLink(me="tg:1", name="Я", account="telegram", label="Telegram", prefix="tg:",
              can={"phone", "links", "search", "react", "forward"}, hosts=("t.me",))
SASHA = tg.person("tg:77", "Внук Саша", contact=True, phone="+79005556677")
tg.person("tg:88", "Анна", phone="+79001112233")
tg.split = True
sasha = tg.dialog(SASHA)
tg.say(sasha, "Привет из Telegram", SASHA)
tg.group("tg:-5", "Клуб", kind="CHANNEL", joined=False, link="https://t.me/club")
bm.SETTINGS.set("account_telegram", True)  # switched on: the others start off
ui = UI()
B = bm.Backend(ui, [fake, tg])
B.start()
until(lambda: len(said(ui, "show_chats")) == 2)
lists = {a: {s["id"]: s for s in ss} for a, ss in said(ui, "show_chats")}
assert set(lists["max"]) == {anna} and set(lists["telegram"]) == {sasha}
assert lists["telegram"][sasha]["account"] == "telegram" and lists["telegram"][sasha]["title"] == "Внук Саша"
assert B.of(anna).id == "max" and B.of(sasha).id == "telegram" and B.of(SASHA).id == "telegram"
assert B.label("telegram") == "Telegram" and not B.can("telemetry", sasha) and B.can("telemetry", anna)
assert back(B.history(sasha))[0][-1]["text"] == "Привет из Telegram" and not fake.asked("history")
assert back(B.send(sasha, "Как дела?"))["text"] == "Как дела?" and tg.asked("send")[-1]["chat_id"] == sasha
[p] = back(B.find_phone("+79005556677"))  # not in MAX: Telegram has them
assert p["chat"] == sasha and p["label"] == "Telegram"
assert [(p["chat"], p["account"]) for p in back(B.find_phone("+79001112233"))] == \
    [(anna, "max"), ("tg:88", "telegram")]  # in both: one each
assert back(B.link_info("https://t.me/club"))["title"] == "Клуб" and not fake.asked("link_info")
fake.group(-90, "Клубника", kind="CHANNEL", joined=False, link="https://max.ru/berry")
found = back(B.search("клуб"))  # both messengers' channels, each saying whose
assert [(f["id"], f["account"], f["link"]) for f in found] == \
    [(-90, "max", "https://max.ru/berry"), ("tg:-5", "telegram", "https://t.me/club")]
back(B.log([{"event": "GO"}]))
assert fake.asked("log") and not tg.asked("log")  # telemetry is MAX's only
assert os.path.exists(os.path.join(bm.DATA, "telegram", "known.json"))  # its files apart
assert "tg:77" not in bm.load_json(bm.KNOWN, [])
tg.files["tg:voice:77:1"] = b"OggS"
got = []  # Media's worker thread asks
dl = os.path.join(bm.PHOTOS, "dl.part")
t = threading.Thread(target=lambda: got.append(B.download("tg:voice:77:1", dl)))
t.start()
until(lambda: got)
assert open(dl, "rb").read() == b"OggS" and tg.asked("download") == [{"ref": "tg:voice:77:1"}]
pic = os.path.join(bm.PHOTOS, "pic.jpg")
with open(pic, "wb") as fh:
    fh.write(b"jpeg")
sent = back(B.send(sasha, "Смотри", [bm.attachment(pic), bm.attachment(pic)]))  # each a message
assert [m["text"] for m in sent] == ["Смотри", ""] and len(B.cache.read(sasha)) == 4
gone = sent[0]["id"]
tg.msgs[sasha] = [m for m in tg.msgs[sasha] if m.id != gone]
tg._push(B.accounts["telegram"].on_delete(None, [gone]))  # Telegram tells no chat but a channel's
until(lambda: any(a[:2] == (sasha, [gone]) for a in said(ui, "deleted")))
assert gone not in [m["id"] for m in B.cache.read(sasha)]
tg.drop()  # one messenger without a connection: the other is asked all the same
until(lambda: ("telegram", False) in said(ui, "connected"))
got = []
B.run(B.send(sasha, "без связи"), lambda res, err: got.append(err))
B.run(B.send(anna, "через MAX"), lambda res, err: got.append(err))
until(lambda: len(got) == 2)
assert isinstance(got[0], bm.Offline) and got[1] is None
got = []
B.run(B.send("wa:1", "нет такого"), lambda res, err: got.append(err))  # no such account
until(lambda: got)
assert isinstance(got[0], bm.Offline)
# a login's list replaces only that account's chats
L = bm.ChatList(os.path.join(bm.PHOTOS, "two.json"), os.path.join(bm.DATA, "two-prefs.json"))
L.replace(list(lists["max"].values()), "max")
L.replace(list(lists["telegram"].values()), "telegram")
L.replace([], "telegram")
assert set(L.chats) == {anna}
ok("two messengers")

# --- the message cache: in memory, on disk a little later, read back by a new one -----------------
c = bm.MessageCache(os.path.join(bm.PHOTOS, "cache-test"), delay=0.05)
c.add(7, [{"id": i, "time": i, "text": "t%d" % i} for i in range(bm.KEEP + 5)])
assert [m["id"] for m in c.read(7)] == list(range(5, bm.KEEP + 5))  # the newest KEEP
c.read(7)[0]["text"] = "changed outside"  # a copy: the cache keeps its own
assert c.read(7)[0]["text"] == "t5"
assert not os.path.exists(c._path(7))  # not written at once
until(lambda: os.path.exists(c._path(7)))
assert oct(os.stat(c._path(7)).st_mode & 0o777) == "0o600"
c.react(7, 6, [["👍", 1]], "👍")
c.forget(7, [5])
c.flush()  # the program's end: what is left goes now
fresh = bm.MessageCache(c.folder)
got = fresh.read(7)
assert got[0]["id"] == 6 and got[0]["reactions"] == [["👍", 1]] and got[0]["yours"] == "👍"
fresh.drop(7)
assert fresh.read(7) == [] and not os.path.exists(c._path(7))
c.add("tg:5", [{"id": 1, "time": 1}])  # another messenger's chat: a folder of its own
c.flush()
assert c._path("tg:5") == os.path.join(c.folder, "tg", "5.json") and os.path.exists(c._path("tg:5"))
assert bm.MessageCache(c.folder).read("tg:5") == [{"id": 1, "time": 1}]
c.add(8, [{"id": 1, "time": 1}])
c.drop(8)  # dropped before its write: nothing comes back on disk
time.sleep(0.15)
assert not os.path.exists(c._path(8))
# the disk written without the lock: a read meanwhile does not wait for it
c.add(9, [{"id": 1, "time": 1}])
c.write_lock.acquire()  # a slow disk, say
writing = threading.Thread(target=c.flush)
writing.start()
time.sleep(0.05)
began = time.monotonic()
assert c.read(9) == [{"id": 1, "time": 1}] and time.monotonic() - began < 0.05
c.write_lock.release()
writing.join()
assert os.path.exists(c._path(9))
# a chat that cannot be written does not keep the others from the disk
c.add(11, [{"id": 1, "time": 1, "bad": object()}])
c.add(12, [{"id": 1, "time": 1}])
c.flush()
assert os.path.exists(c._path(12)) and not os.path.exists(c._path(11))
# a chat dropped while its write was on its way: the drop wins
c.add(10, [{"id": 1, "time": 1}])
real_fdopen = bm.os.fdopen
def dropping(fd, *a, **k):
    c.drop(10)  # comes in while the text goes to disk
    return real_fdopen(fd, *a, **k)
from unittest.mock import patch  # noqa: E402
with patch.object(bm.os, "fdopen", dropping):
    c.flush()
assert not os.path.exists(c._path(10)) and not os.path.exists(c._path(10) + ".new")
ok("the message cache")

# --- a deletion naming no chat, an emptied known.json, a page of no times ----
d = bm.MessageCache(tempfile.mkdtemp())
d.add("tg:1", [{"id": 101, "time": 1}])
d.add("tg:2", [{"id": 202, "time": 1}])
d.add("tg:3", [{"id": 303, "time": 1}])
d.flush()
d2 = bm.MessageCache(d.folder)
d2.read("tg:1")  # in memory; tg:2 and tg:3 only on disk
assert sorted(d2.chats_with({101, 202}, ["tg:1", "tg:2", "tg:3", "tg:4"])) == ["tg:1", "tg:2"]
assert set(d2.chats) == {"tg:1"}  # the others' files read, not kept
with open(d2._path("tg:3"), "w") as fh:
    fh.write("not json")
assert d2.chats_with({303}, ["tg:3"]) == []
os.makedirs(os.path.dirname(bm.KNOWN), exist_ok=True)
with open(bm.KNOWN, "w"):
    pass  # left empty by a power loss
assert not bm.Backend(UI(), fake).accounts["max"].seeded  # seeded again at the login
bm.save_json(bm.KNOWN, [ANNA])
assert bm.Backend(UI(), fake).accounts["max"].seeded
bm.save_json(bm.KNOWN, [])  # nobody known is a state: strangers stay strangers
bs = bm.Backend(UI(), fake)
assert bs.accounts["max"].seeded
run(bs.accounts["max"].on_login(fake.me, list(fake.rooms.values()), [], fake.agent, 7))
stranger = next(r for r in fake.rooms.values() if r.kind == "DIALOG")  # nobody known: any dialog
assert bs.accounts["max"].known == set() and bs.accounts["max"].summary(stranger)["stranger"]
for broken in ('{"ids": [1]}', "[1, 2"):
    with open(bm.KNOWN, "w") as fh:
        fh.write(broken)
    assert not bm.Backend(UI(), fake).accounts["max"].seeded
bz = bm.Backend(UI(), fake)
zero = bm.Chat(id=999, kind="CHAT", title="без времени", members=[], count=0, unread=0, last=None, time=0)
pages = []
async def no_times(marker):
    pages.append(marker)
    return [zero]
bz.accounts["max"].link.chats_page = no_times
run(bz.accounts["max"].on_login(fake.me, list(fake.rooms.values()), [], fake.agent, 7))
assert pages == [None] and 999 in bz.accounts["max"].chats  # no ValueError, the list is told
ok("a deletion without its chat reads no file into memory; an empty known.json seeds again; a page without times")
