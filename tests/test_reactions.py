# SPDX-License-Identifier: GPL-3.0-or-later
"""Reaction subscriptions, snapshots and live updates, without a real account."""
import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from common import load, ok

bm = load()
from gi.repository import GLib
from pymax.protocol import Opcode


class UI:
    def __init__(self):
        self.updates = []

    def reacted(self, *args):
        self.updates.append(args)


def drain():
    while GLib.MainContext.default().iteration(False):
        pass


class Link:
    account, label, prefix = "max", "MAX", None

    def __init__(self):
        self.calls = []
        self.subscribed = set()
        self.state = {9: ([], None)}
        self.waiting = None
        self.reads = 0

    async def subscribe(self, chat, on):
        self.calls.append((chat, on))
        (self.subscribed.add if on else self.subscribed.discard)(chat)

    async def reactions(self, chat, ids):
        self.reads += 1
        got = {i: self.state[i] for i in ids if i in self.state}
        if self.waiting:
            await self.waiting.wait()
        return got


async def wait(check):
    for _ in range(100):
        drain()
        if check():
            return
        await asyncio.sleep(.005)
    raise AssertionError("reaction update did not arrive")


async def lifecycle():
    link, ui = Link(), UI()
    backend = bm.Backend(ui, link)
    account = backend.accounts["max"]
    account.online = True
    account.cache.add(13, [{"id": 9, "time": 1, "reactions": [], "yours": None}])
    await backend.watch_reactions(13, [9])
    await wait(lambda: 13 in link.subscribed)
    # The server sends another person's reaction only on the subscribed chat.
    if 13 in link.subscribed:
        await account.on_reaction(13, 9, [["❤️", 1]])
    await wait(lambda: account.cache.read(13)[0]["reactions"] == [["❤️", 1]])
    # No duplicate lease or repeated snapshot for the same visible messages.
    before = len(link.calls)
    await backend.watch_reactions(13, [9])
    assert len(link.calls) == before
    # Leaving renews neither the old subscription nor its UI updates.
    await backend.watch_reactions(None, [])
    assert not link.subscribed
    # Reconnect restores both the lease and reactions missed while disconnected.
    await backend.watch_reactions(13, [9])
    await wait(lambda: 13 in link.subscribed)
    await account.reaction_watch.pause()
    account.online = False
    link.subscribed.clear()  # connection gone, server leases gone
    link.state[9] = ([["🔥", 2]], "🔥")
    account.online = True
    await account.reaction_watch.resume()
    await wait(lambda: account.cache.read(13)[0]["yours"] == "🔥")
    assert account.cache.read(13)[0]["reactions"] == [["🔥", 2]]
    await backend.watch_reactions(None, [])


async def lease_and_switch():
    link = Link()
    account = bm.Backend(UI(), link).accounts["max"]
    account.online = True
    with patch.object(bm, "CHAT_LEASE", .02):
        await account.reaction_watch.select(13, [9])
        await wait(lambda: len(link.calls) >= 3)
        assert link.calls == [(13, True)] * len(link.calls)
        assert link.reads == 1  # renew the lease, never poll the counters
        # A slow snapshot is cancelled when another chat is shown.
        link.waiting = asyncio.Event()
        await account.reaction_watch.select(14, [9])
        await wait(lambda: 14 in link.subscribed)
        await account.reaction_watch.select(15, [9])
        await wait(lambda: 15 in link.subscribed)
        assert link.subscribed == {15}
        await account.reaction_watch.select(None, [])
        assert not link.subscribed and not account.reaction_reads


async def snapshot_race():
    link, ui = Link(), UI()
    account = bm.Backend(ui, link).accounts["max"]
    account.online = True
    account.cache.add(13, [{"id": 9, "time": 1, "reactions": [], "yours": None}])
    link.waiting = asyncio.Event()
    snapshot = asyncio.create_task(account.reactions(13, [9]))
    await asyncio.sleep(0)
    await account.on_reaction(13, 9, [["👍", 1]], "👍")
    link.waiting.set()
    await snapshot
    drain()
    assert account.cache.read(13)[0]["reactions"] == [["👍", 1]]
    assert account.cache.read(13)[0]["yours"] == "👍"
    assert ui.updates[-1][2:] == ([["👍", 1]], "👍")


async def wire():
    sent, events = [], []
    async def invoke(opcode, payload):
        sent.append((int(opcode), payload))
    link = bm.PyMaxLink("/nonexistent")
    link.client = SimpleNamespace(_app=SimpleNamespace(invoke=invoke))
    await link.subscribe(13, True)
    await link.subscribe(13, False)
    assert sent == [(75, {"chatId": 13, "subscribe": True}),
                    (75, {"chatId": 13, "subscribe": False})]
    class Events:
        async def on_reaction(self, *args):
            events.append(args)
    link.events = Events()
    for info in ({"counters": [{"reaction": "❤️", "count": 1}], "yourReaction": "❤️"}, {}):
        link._peek(SimpleNamespace(opcode=Opcode.NOTIF_MSG_YOU_REACTED,
                                   payload={"chatId": 13, "messageId": 9, "reactionInfo": info}))
        await asyncio.sleep(0)
    assert events == [(13, 9, [["❤️", 1]], "❤️"), (13, 9, [], None)]
    # Exercise the exact PyMax 2.4.1 mapper that throws on a real numeric id.
    # Handled reaction frames must never be dispatched into it a second time.
    from pymax.dispatch.mapping import EventMapper
    from pymax.dispatch.enums import EventType
    from pymax.protocol.enums import Command
    raw = []
    class Dispatcher:
        async def dispatch(self, frame):
            raw.append(frame.opcode)
            EventMapper(None).map(EventType.REACTION_UPDATE, frame)
    link.client._app.dispatcher = Dispatcher()
    link._watch_deletions(link.client)
    frame = SimpleNamespace(opcode=Opcode.NOTIF_MSG_REACTIONS_CHANGED, cmd=Command.REQUEST,
                            payload={"chatId": 13, "messageId": 9,
                                     "counters": [{"reaction": "👍", "count": 1}]})
    await link.client._app.dispatcher.dispatch(frame)
    await asyncio.sleep(0)
    assert raw == [] and events[-1] == (13, 9, [["👍", 1]])


asyncio.run(lifecycle())
ok("a visible chat subscribes, leaving unsubscribes, reconnect restores reactions")
asyncio.run(snapshot_race())
ok("an older reaction snapshot never overwrites a live update")
asyncio.run(lease_and_switch())
ok("leases renew without polling; switching cancels a slow snapshot")
asyncio.run(wire())
ok("MAX subscription frames and account reaction changes from another client")
