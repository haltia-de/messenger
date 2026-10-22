# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mikhail Nevskiy
"""A small MAX in memory, the other link beside haltia-messenger's PyMaxLink (see
CONTEXT.md: Связь с MAX). Tests and the demo build its state, run the real
Backend and window on it, and read back what was asked of it in calls.

It hands out the link's own Person, Chat and Message, as PyMaxLink does, so
the code above the link cannot tell the two apart. Everything is plain and
immediate; events (a message, someone's reaction) come when a test calls
incoming() or reaction(), from any thread. Load haltia-messenger first
(common.load()): the entities are its."""
import asyncio
import dataclasses
import itertools
import os
import time

from haltia_messenger import Chat, Message, Person

ME = 1


def now_ms():
    return int(time.time() * 1000)


def user(uid, name):
    return Person(uid, name)


class FakeLink:
    hosts = ("max.ru",)
    can = frozenset({"phone", "links", "search", "react", "forward", "telemetry", "invites"})
    seen_by = "time"  # as MAX: a chat's seen is a time

    def dialog_id(self, peer):
        """A dialog's id: as MAX numbers it (own id XOR theirs), or, with a
        prefix (a messenger of string ids, as Telegram's), the person's."""
        return peer if self.prefix else self.me.id ^ peer

    def dialog_of(self, me, user):  # the link's: as above, from either side
        return user if self.prefix else me ^ user

    def __init__(self, me=ME, name="Я", account="max", label="MAX", prefix=None, can=None,
                 hosts=None):
        self.account, self.label, self.prefix = account, label, prefix  # as PyMaxLink's
        if can is not None:
            self.can = frozenset(can)
        if hosts is not None:
            self.hosts = tuple(hosts)
        self.me = user(me, name)
        self.people = {me: self.me}  # (not self.users: the link's operation)
        self.contacts = set()  # ids
        self.phones = {}  # "+7…" -> user id
        self.rooms = {}  # chat id -> Chat (not self.chats: that is the link's operation)
        self.msgs = {}  # chat id -> [Message], oldest first
        self.links = {}  # https://max.ru/… -> Chat, not joined yet
        self.media = {}  # (chat id, msg id, kind) -> link MAX would give
        self.files = {}  # ref -> bytes its download() writes (a messenger without links)
        self.counts = True  # react() answers with counts (MAX does not always)
        self.calls = []  # (operation, args) asked of MAX, in order
        self.ids = itertools.count(100000)
        self.loop = self.events = self.ended = None
        self.runs = 0  # how many times the program started the link
        self.agent = "Mozilla/5.0 (X11; Linux x86_64) FakeLink"

    # --- building the state ---------------------------------------------------
    def person(self, uid, name, contact=False, phone=None, photo=None):
        self.people[uid] = Person(uid, name, photo)
        if contact:
            self.contacts.add(uid)
        if phone:
            self.phones[phone] = uid
        return uid

    def dialog(self, peer, unread=0):
        """The dialog with someone (numbered as MAX does: own id XOR theirs)."""
        cid = self.dialog_id(peer)
        self._chat(cid, "DIALOG", None, {self.me.id: 0, peer: 0}, unread)
        return cid

    def group(self, cid, title, kind="CHAT", members=(), unread=0, joined=True, link=None):
        parts = {self.me.id: 0} if joined else {}
        parts.update({m: 0 for m in members})
        chat = self._chat(cid, kind, title, parts, unread, keep=joined)
        if link:
            self.links[link] = chat
            chat.link = link
        return cid

    def _chat(self, cid, kind, title, parts, unread, keep=True):
        chat = Chat(cid, kind, title, list(parts), len(parts), unread)
        if keep:
            self.rooms[cid] = chat
        self.msgs.setdefault(cid, [])
        return chat

    def say(self, cid, text="", sender=None, t=None, attaches=(), reactions=(), yours=None):
        """A message already in a chat (no event); attaches as made by
        photo(), audio(), video(), file(), sticker() below."""
        msg = Message(next(self.ids), cid, sender or self.me.id, t or now_ms(), text,
                      reactions=[list(r) for r in reactions], yours=yours)
        for a in attaches:
            msg.parts.append(a["part"])
            if "call" in a:
                msg.call = dict(a["call"])
            elif "photo" in a:
                msg.photos.append(a["photo"])
            elif "media" in a:
                msg.media.append(dict(a["media"]))
            else:
                msg.notes.append(a["part"])
        self.msgs.setdefault(cid, []).append(msg)
        self.msgs[cid].sort(key=lambda m: m.time)
        chat = self.rooms.get(cid)
        if chat is not None and (chat.last is None or chat.last.time <= msg.time):
            chat.last = msg
            chat.time = msg.time
        return msg

    # --- events, as MAX would push them -----------------------------------------
    def incoming(self, cid, text, sender, **kw):
        """A new message comes (from any thread); returns it."""
        msg = self.say(cid, text, sender, **kw)
        self._push(self.events.on_message(msg))
        return msg

    def deleted(self, cid, msg_ids):
        """Messages deleted for everyone (by their sender, elsewhere)."""
        self.msgs[cid] = [m for m in self.msgs.get(cid, []) if m.id not in msg_ids]
        chat = self.rooms.get(cid)
        if chat is not None and chat.last is not None and chat.last.id in msg_ids:
            chat.last = self.msgs[cid][-1] if self.msgs[cid] else None
        self._push(self.events.on_delete(cid, list(msg_ids)))

    def peer_read(self, cid, mark):
        """The others read the chat up to mark (MAX's NOTIF_MARK). The chats
        are the same objects the account holds: it keeps the mark itself."""
        self._push(self.events.on_read(cid, mark))

    def reaction(self, cid, msg_id, reactions):
        self._push(self.events.on_reaction(cid, msg_id, [list(r) for r in reactions]))

    def drop(self):
        """The connection is lost for a while (PyMax connects again by itself:
        back() is that)."""
        self._push(self.events.on_disconnect("ConnectionError('fake')"))

    def back(self):
        self._push(self.events.on_login(self.me, list(self.rooms.values()),
                                        [self.people[u] for u in self.contacts], self.agent, 7))

    def give_up(self, why="fake: gave up"):
        """run() raises, as PyMax's start does when it gives up for good;
        the program starts the link again (run() once more)."""
        self.loop.call_soon_threadsafe(self.ended.set_exception, RuntimeError(why))

    def _push(self, coro):
        def failed(fut):  # an event the program could not take: the test must see it
            if fut.exception() is not None:
                import traceback
                traceback.print_exception(fut.exception())
        asyncio.run_coroutine_threadsafe(coro, self.loop).add_done_callback(failed)

    # --- the link -----------------------------------------------------------------
    def _call(self, name, **args):
        self.calls.append((name, args))

    def asked(self, name):
        """The arguments of each call of one operation, in order."""
        return [a for n, a in self.calls if n == name]

    def scan(self):
        """The QR code scanned on the phone: the login goes on."""
        self.loop.call_soon_threadsafe(self.scanned.set_result, True)

    async def run(self, events):
        self.loop, self.events = asyncio.get_running_loop(), events
        self.runs += 1
        self.ended = self.loop.create_future()  # give_up() ends this run
        if self.refuse is not None:  # the keyring closed, say
            raise self.refuse
        if not self.kept:  # no login kept: a QR code, till scan()
            self.scanned = self.loop.create_future()
            await events.on_qr("https://max.ru/:login/fake")
            await self.scanned
            wrong = False
            while self.password is not None:  # a cloud password, as Telegram's
                if await events.on_password(wrong) == self.password:
                    break
                wrong = True
            self.kept = True
        await events.on_login(self.me, list(self.rooms.values()),
                              [self.people[u] for u in self.contacts], self.agent, 7)
        await self.ended  # connected till then

    kept = True  # a login is kept: the program starts it without a QR code
    password = None  # the account's cloud password, asked after the QR code (Telegram's)
    split = False  # each file sent is a message of its own (Telegram's way): send() gives a list
    refuse = None  # an exception run() raises at once (Locked: the keyring closed)

    async def signed_in(self):
        return self.kept

    async def logout(self):
        self._call("logout")
        self.kept = False

    async def chats_page(self, marker=None):
        self._call("chats_page", marker=marker)
        page = sorted(self.rooms.values(), key=lambda c: -c.time)
        return [c for c in page if marker is None or c.time < marker]

    async def chats(self, ids):
        self._call("chats", ids=list(ids))
        return [self.rooms[i] for i in ids if i in self.rooms]

    async def users(self, ids):
        return [self.people[i] for i in ids if i in self.people]

    async def find_phone(self, phone):
        self._call("find_phone", phone=phone)
        if phone not in self.phones:
            raise LookupError("not in MAX")
        return self.people[self.phones[phone]]

    async def add_contact(self, user_id):
        self._call("add_contact", user_id=user_id)
        self.contacts.add(user_id)
        return self.people[user_id]

    async def link_info(self, link):
        self._call("link_info", link=link)
        return self.links.get(link)

    async def search(self, query):
        """Public channels and groups with a link, by a part of their title."""
        self._call("search", query=query)
        return [c for c in self.links.values() if query.casefold() in (c.title or "").casefold()]

    async def join(self, link):
        self._call("join", link=link)
        chat = self.links[link]
        chat.members.append(self.me.id)
        self.rooms[chat.id] = chat
        return chat

    async def leave(self, chat_id):
        self._call("leave", chat_id=chat_id)
        chat = self.rooms.get(chat_id)
        if chat is not None and self.me.id in chat.members:
            chat.members.remove(self.me.id)

    async def delete(self, chat_id, last_event_time=None):
        self._call("delete", chat_id=chat_id)
        self.rooms.pop(chat_id, None)

    async def history(self, chat_id, backward, before=None):
        self._call("history", chat_id=chat_id, backward=backward, before=before)
        msgs = [m for m in self.msgs.get(chat_id, []) if before is None or m.time < before]
        return msgs[-backward:]

    async def read(self, chat_id, msg_id):
        self._call("read", chat_id=chat_id, msg_id=msg_id)
        if chat_id in self.rooms:
            self.rooms[chat_id].unread = 0

    async def send(self, chat_id, text, files=(), reply_to=None):
        more = {"reply_to": reply_to} if reply_to else {}
        if self.split and files:
            sent = []
            for n, f in enumerate(files):
                self.split = False
                try:
                    sent.append(await self.send(chat_id, text if n == 0 else "", [f],
                                                reply_to if n == 0 else None))
                finally:
                    self.split = True
            return sent
        if files:  # as MAX would show them back: a photo by a link of its own
            self._call("send", chat_id=chat_id, text=text,
                       files=[(f["kind"], os.path.basename(f["path"]), f.get("duration"))
                              for f in files], **more)
        else:
            self._call("send", chat_id=chat_id, text=text, **more)
        if chat_id not in self.rooms:  # a dialog's first message starts it
            peer = self.dialog_of(self.me.id, chat_id)
            self._chat(chat_id, "DIALOG", None, {self.me.id: 0, peer: 0}, 0)
        attaches = []
        for f in files:
            name = os.path.basename(f["path"])
            if f["kind"] == "photo":
                attaches.append(photo("https://i.oneme.ru/sent/" + name))
            elif f["kind"] == "voice":
                attaches.append(audio("https://vd.okcdn.ru/sent/" + name, f["duration"] // 1000))
            else:
                attaches.append(file(next(self.ids), f.get("name") or name, os.path.getsize(f["path"])))
        msg = self.say(chat_id, text, self.me.id, attaches=attaches)
        if reply_to:  # as MAX shows an answer back: what it answers carried along
            quoted = next((m for m in self.msgs.get(chat_id, []) if m.id == reply_to), None)
            msg.reply = {"id": reply_to, "sender": quoted.sender if quoted else None,
                         "text": quoted.text if quoted else ""}
        return msg

    async def forward(self, chat_id, msg_id, from_chat_id):
        self._call("forward", chat_id=chat_id, msg_id=msg_id, from_chat_id=from_chat_id)
        src = next(m for m in self.msgs[from_chat_id] if m.id == msg_id)
        origin = self.rooms.get(from_chat_id)
        msg = dataclasses.replace(
            src, id=next(self.ids), chat=chat_id, sender=self.me.id, time=now_ms(),
            photos=list(src.photos), media=[dict(i) for i in src.media], notes=list(src.notes),
            parts=list(src.parts), reactions=[], yours=None,
            fwd={"chat": origin.title if origin is not None else None, "sender": src.sender})
        self.msgs.setdefault(chat_id, []).append(msg)
        if chat_id in self.rooms:
            self.rooms[chat_id].last = msg
        return msg

    async def react(self, chat_id, msg_id, emoji):
        self._call("react", chat_id=chat_id, msg_id=msg_id, emoji=emoji)
        msg = next(m for m in self.msgs[chat_id] if m.id == msg_id)
        counts = dict(msg.reactions)
        if msg.yours:
            counts[msg.yours] -= 1
        if emoji:
            counts[emoji] = counts.get(emoji, 0) + 1
        msg.reactions = [[e, n] for e, n in counts.items() if n > 0]
        msg.yours = emoji
        return ([list(r) for r in msg.reactions], emoji) if self.counts else None

    async def media_url(self, chat_id, msg_id, item):
        self._call("media_url", chat_id=chat_id, msg_id=msg_id, kind=item["kind"])
        return self.media.get((chat_id, msg_id, item["kind"]))

    async def download(self, ref, path):
        self._call("download", ref=ref)
        with open(path, "wb") as fh:
            fh.write(self.files[ref])

    invites_value = "CONTACTS"  # CHATS_INVITE as MAX sends it at login

    def invites(self):
        return self.invites_value

    async def log(self, events):
        self._call("log", events=events)


# attachments, as a link hands them out in a Message (say()'s attaches)
def audio(url, duration=7):
    return {"part": "голосовое сообщение",
            "media": {"kind": "audio", "url": url, "duration": duration}}


def video(video_id, thumb="", duration=42):
    return {"part": "видео",
            "media": {"kind": "video", "id": video_id, "thumb": thumb, "duration": duration}}


def file(file_id, name, size):
    """A file; one named like audio plays in the bubble (its link asked when played)."""
    if name.lower().endswith((".mp3", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".wav", ".flac")):
        item = {"kind": "audio", "url": None, "file": file_id, "name": name, "size": size,
                "duration": 0}
    else:
        item = {"kind": "file", "id": file_id, "name": name, "size": size}
    return {"part": "файл «%s»" % name, "media": item}


def photo(url):
    return {"part": "", "photo": url}


def call(video=False, end="HUNGUP", duration=0):
    """A call's record, as MAX puts one in the chat (CALL attach)."""
    return {"part": "звонок", "call": {"video": video, "end": end, "duration": duration}}


def sticker():
    return {"part": "стикер"}
