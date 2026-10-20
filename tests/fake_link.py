# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2026 Mikhail Nevskiy
"""A small MAX in memory, the other link beside haltia-messenger's PyMaxLink (see
CONTEXT.md: Связь с MAX). Tests and the demo build its state, run the real
Backend and window on it, and read back what was asked of it in calls.

It hands out PyMax's own objects, as PyMaxLink does, so the code above the
link cannot tell the two apart. Everything is plain and immediate; events
(a message, someone's reaction) come when a test calls incoming() or
reaction(), from any thread."""
import asyncio
import itertools
import time

from pymax.types.domain import Chat, Message, ReactionInfo, User

ME = 1


def now_ms():
    return int(time.time() * 1000)


def user(uid, name):
    return User.model_validate({"id": uid, "names": [{"name": name, "type": "CUSTOM"}]})


class FakeLink:
    def __init__(self, me=ME, name="Я"):
        self.me = user(me, name)
        self.people = {me: self.me}  # (not self.users: the link's operation)
        self.contacts = set()  # ids
        self.phones = {}  # "+7…" -> user id
        self.rooms = {}  # chat id -> Chat (not self.chats: that is the link's operation)
        self.msgs = {}  # chat id -> [Message], oldest first
        self.links = {}  # https://max.ru/… -> Chat, not joined yet
        self.media = {}  # (chat id, msg id, kind) -> link MAX would give
        self.counts = True  # react() answers with counts (MAX does not always)
        self.calls = []  # (operation, args) asked of MAX, in order
        self.ids = itertools.count(100000)
        self.loop = self.events = self.ended = None
        self.runs = 0  # how many times the program started the link
        self.agent = "Mozilla/5.0 (X11; Linux x86_64) FakeLink"

    # --- building the state ---------------------------------------------------
    def person(self, uid, name, contact=False, phone=None):
        self.people[uid] = user(uid, name)
        if contact:
            self.contacts.add(uid)
        if phone:
            self.phones[phone] = uid
        return uid

    def dialog(self, peer, unread=0):
        """The dialog with someone (numbered as MAX does: own id XOR theirs)."""
        cid = self.me.id ^ peer
        self._chat(cid, "DIALOG", None, {self.me.id: 0, peer: 0}, unread)
        return cid

    def group(self, cid, title, kind="CHAT", members=(), unread=0, joined=True, link=None):
        parts = {self.me.id: 0} if joined else {}
        parts.update({m: 0 for m in members})
        chat = self._chat(cid, kind, title, parts, unread, keep=joined)
        if link:
            self.links[link] = chat
        return cid

    def _chat(self, cid, kind, title, parts, unread, keep=True):
        chat = Chat.model_validate({"id": cid, "type": kind, "status": "ACTIVE", "owner": self.me.id,
                                    "participants": parts, "title": title, "newMessages": unread,
                                    "participantsCount": len(parts)})
        if keep:
            self.rooms[cid] = chat
        self.msgs.setdefault(cid, [])
        return chat

    def say(self, cid, text="", sender=None, t=None, attaches=(), reactions=(), yours=None):
        """A message already in a chat (no event)."""
        msg = Message.model_validate({
            "id": next(self.ids), "chatId": cid, "sender": sender or self.me.id, "text": text,
            "time": t or now_ms(), "type": "USER", "attaches": list(attaches),
            "reactionInfo": {"totalCount": sum(n for _e, n in reactions),
                             "counters": [{"reaction": e, "count": n} for e, n in reactions],
                             "yourReaction": yours} if reactions else None})
        self.msgs.setdefault(cid, []).append(msg)
        self.msgs[cid].sort(key=lambda m: m.time)
        chat = self.rooms.get(cid)
        if chat is not None and (chat.last_message is None or chat.last_message.time <= msg.time):
            chat.last_message = msg
            chat.last_event_time = msg.time
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
        if chat is not None and chat.last_message is not None and chat.last_message.id in msg_ids:
            chat.last_message = self.msgs[cid][-1] if self.msgs[cid] else None
        self._push(self.events.on_delete(cid, list(msg_ids)))

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

    async def run(self, events):
        self.loop, self.events = asyncio.get_running_loop(), events
        self.runs += 1
        self.ended = self.loop.create_future()  # give_up() ends this run
        await events.on_login(self.me, list(self.rooms.values()),
                              [self.people[u] for u in self.contacts], self.agent, 7)
        await self.ended  # connected till then

    async def chats_page(self, marker=None):
        self._call("chats_page", marker=marker)
        page = sorted(self.rooms.values(), key=lambda c: -(c.last_event_time or 0))
        return [c for c in page if marker is None or (c.last_event_time or 0) < marker]

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

    async def join(self, link):
        self._call("join", link=link)
        chat = self.links[link]
        chat.participants[self.me.id] = 0
        self.rooms[chat.id] = chat
        return chat

    async def leave(self, chat_id):
        self._call("leave", chat_id=chat_id)
        chat = self.rooms.get(chat_id)
        if chat is not None:
            chat.participants.pop(self.me.id, None)

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
            self.rooms[chat_id].new_messages = 0

    async def send(self, chat_id, text):
        self._call("send", chat_id=chat_id, text=text)
        if chat_id not in self.rooms:  # a dialog's first message starts it
            peer = chat_id ^ self.me.id
            self._chat(chat_id, "DIALOG", None, {self.me.id: 0, peer: 0}, 0)
        return self.say(chat_id, text, self.me.id)

    async def forward(self, chat_id, msg_id, from_chat_id):
        self._call("forward", chat_id=chat_id, msg_id=msg_id, from_chat_id=from_chat_id)
        src = next(m for m in self.msgs[from_chat_id] if m.id == msg_id)
        origin = self.rooms.get(from_chat_id)
        msg = Message.model_validate({
            "id": next(self.ids), "chatId": chat_id, "sender": self.me.id, "text": "",
            "time": now_ms(), "type": "USER",
            "link": {"type": "FORWARD", "chatId": from_chat_id,
                     "chatName": origin.title if origin is not None else None,
                     "message": src.model_dump(by_alias=True)}})
        self.msgs.setdefault(chat_id, []).append(msg)
        if chat_id in self.rooms:
            self.rooms[chat_id].last_message = msg
        return msg

    async def react(self, chat_id, msg_id, emoji):
        self._call("react", chat_id=chat_id, msg_id=msg_id, emoji=emoji)
        msg = next(m for m in self.msgs[chat_id] if m.id == msg_id)
        info = msg.reaction_info or ReactionInfo()
        counts = {c.reaction: c.count for c in info.counters}
        if info.your_reaction:
            counts[info.your_reaction] -= 1
        if emoji:
            counts[emoji] = counts.get(emoji, 0) + 1
        msg.reaction_info = ReactionInfo.model_validate({
            "totalCount": sum(counts.values()), "yourReaction": emoji,
            "counters": [{"reaction": e, "count": n} for e, n in counts.items() if n > 0]})
        return msg.reaction_info if self.counts else None

    async def media_url(self, chat_id, msg_id, item):
        self._call("media_url", chat_id=chat_id, msg_id=msg_id, kind=item["kind"])
        return self.media.get((chat_id, msg_id, item["kind"]))

    invites_value = "CONTACTS"  # CHATS_INVITE as MAX sends it at login

    def invites(self):
        return self.invites_value

    async def log(self, events):
        self._call("log", events=events)


# attachments as MAX sends them
def audio(url, duration=7):
    return {"_type": "AUDIO", "url": url, "duration": duration}


def video(video_id, thumb="", duration=42):
    return {"_type": "VIDEO", "videoId": video_id, "thumbnail": thumb, "token": "t",
            "videoType": 0, "width": 640, "height": 360, "duration": duration}


def file(file_id, name, size):
    return {"_type": "FILE", "fileId": file_id, "name": name, "size": size, "token": "t"}


def photo(url):
    return {"_type": "PHOTO", "baseUrl": url, "photoId": 1, "width": 640, "height": 480,
            "photoToken": "t"}
