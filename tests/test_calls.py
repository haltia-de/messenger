# SPDX-License-Identifier: GPL-3.0-or-later
"""Calls on a fake signalling service: no account, network or microphone."""
import asyncio
import base64
import json
from common import load, ok

bm = load()


def literal(value):
    data = json.dumps(value).encode()
    n = len(data) - 15
    block = bytes([min(len(data), 15) << 4])
    if n >= 0:
        block += bytes([255]) * (n // 255) + bytes([n % 255])
    return str(len(data)) + ":" + base64.b64encode(block + data).decode()


params = {"wse": "wss://videowebrtc.okcdn.ru/ws2", "trnu": "expires:peer",
          "tkn": "synthetic", "endpoint": "wss://videowebrtc.okcdn.ru/ws2?token=synthetic"}
assert bm.call_params(literal(params)) == params
for vcp in ("999999:aA==", "4:AAAA", "1:!", "0:"):
    try:
        bm.call_params(vcp)
    except (ValueError, IndexError):
        pass
    else:
        raise AssertionError(vcp)
# An overlapping LZ4 match: one literal 'a', repeated four times, last literal.
assert bm.call_params("7:" + base64.b64encode(bytes([0x20]) + b'"a' + bytes([1, 0, 0x10]) + b'"').decode()) == "aaaaa"
assert "tgt=accept" in bm.call_endpoint(params, "fake", True)
for endpoint in ("ws://videowebrtc.okcdn.ru/ws2", "wss://okcdn.ru.evil/ws2", "wss://example.org/ws2"):
    try:
        bm.call_endpoint({"endpoint": endpoint}, "fake", False)
    except ValueError:
        pass
    else:
        raise AssertionError(endpoint)
ok("bounded invitations and signalling endpoints")


class Audio:
    made = []
    def __init__(self, loop, candidate, state, params):
        self.closed = False
        self.state = state
        self.remote_set = False
        self.candidates = []
        self.made.append(self)
    async def remote(self, value):
        self.remote_set = True
    async def description(self, kind):
        return {"type": kind, "sdp": "synthetic"}
    def add_candidate(self, value):
        self.candidates.append(value)
    def close(self):
        self.closed = True


class Socket:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.sent = []
        self.closed = False
    async def send(self, raw):
        if raw == "pong":
            self.sent.append(raw)
            return
        value = json.loads(raw)
        self.sent.append(value)
        await self.queue.put(json.dumps({"type": "response", "sequence": value["sequence"]}))
    async def recv(self):
        return await self.queue.get()
    async def close(self):
        self.closed = True
    async def __aenter__(self):
        await self.notify("connection", conversation={"topology": "DIRECT", "participants": [
            {"id": "remote", "externalId": {"id": "test-person"}}]})
        return self
    async def __aexit__(self, *args):
        self.closed = True
    async def notify(self, name, **value):
        await self.queue.put(json.dumps(dict(type="notification", notification=name, **value)))
    def commands(self):
        return [v["command"] for v in self.sent if isinstance(v, dict)]


async def until(predicate):
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(.01)
    raise AssertionError("call did not settle")


async def scenario(incoming):
    socket = Socket()
    states = []
    made = len(Audio.made)
    call = bm.VoiceCall("test-call", "test-person", incoming,
                        lambda call, state: states.append(state), audio=Audio,
                        connect=lambda *args, **kwargs: socket)
    run = asyncio.create_task(call.run(dict(params)))
    await until(lambda: "change-participant-state" in socket.commands())
    await socket.queue.put("ping")
    await until(lambda: "pong" in socket.sent)
    if incoming:
        await socket.notify("transmitted-data", participantId="remote", data={
            "sdp": {"type": "offer", "sdp": "synthetic", "p2pRelay": True}})
        await socket.notify("transmitted-data", participantId="remote", data={
            "candidate": {"candidate": "synthetic", "sdpMLineIndex": 0}})
        await asyncio.sleep(.05)
        assert len(Audio.made) == made and "accept-call" not in socket.commands()
        call.job(call.answer())  # the person's Answer tap
    else:
        assert len(Audio.made) == made
        await socket.notify("accepted-call", participantId="remote")
    await until(lambda: "transmit-data" in socket.commands())
    assert len(Audio.made) == made + 1
    if incoming:
        assert Audio.made[-1].remote_set and Audio.made[-1].candidates
        assert socket.commands().index("accept-call") < socket.commands().index("transmit-data")
    Audio.made[-1].state("connected")
    assert states[-1] == "active"
    if incoming:
        await socket.notify("hungup", reason="HUNGUP")
    else:
        await call.end("HUNGUP")
    await until(lambda: call.closed)
    await asyncio.gather(run, return_exceptions=True)
    assert Audio.made[-1].closed and socket.closed and states[-1] == "ended"
    previous = len(socket.sent)
    call.candidate({"candidate": "late"})
    await asyncio.sleep(.02)
    assert len(socket.sent) == previous
    sequences = [v["sequence"] for v in socket.sent if isinstance(v, dict)]
    assert sequences == sorted(set(sequences))
    ok("incoming: consent, early SDP/ICE, ping, remote hangup" if incoming else
       "outgoing: wait for acceptance, local hangup, late ICE")


async def rejection():
    socket = Socket()
    made = len(Audio.made)
    call = bm.VoiceCall("decline", "test-person", True, lambda *args: None,
                        audio=Audio, connect=lambda *args, **kwargs: socket)
    run = asyncio.create_task(call.run(dict(params)))
    await until(lambda: call.socket is not None)
    await call.end("REJECTED")
    await asyncio.gather(run, return_exceptions=True)
    assert len(Audio.made) == made
    assert any(v.get("reason") == "REJECTED" for v in socket.sent if isinstance(v, dict))
    ok("decline without microphone or acceptance")


async def cancelled_before_connect():
    socket = Socket()
    gate = asyncio.Event()
    class Connecting:
        async def __aenter__(self):
            await gate.wait()
            return socket
        async def __aexit__(self, *args):
            await socket.close()
    call = bm.VoiceCall("cancel-before-socket", "test-person", False, lambda *args: None,
                        audio=Audio, connect=lambda *args, **kwargs: Connecting())
    call.start(dict(params))
    await asyncio.sleep(.01)
    await call.end("CANCELED")
    gate.set()
    await call.task
    assert socket.closed
    assert socket.commands() == ["hangup"]
    assert socket.sent[0]["reason"] == "CANCELED"
    ok("cancel while ws2 connects still delivers hangup without media")


async def terminal_events():
    for event, body, expected in (("closed-conversation", {}, "ended"),
                                  ("topology-changed", {"topology": "SERVER"}, "unsupported")):
        socket = Socket()
        states = []
        call = bm.VoiceCall("terminal", "test-person", True,
                            lambda call, state: states.append(state), audio=Audio,
                            connect=lambda *args, **kwargs: socket)
        call.start(dict(params))
        await until(lambda: call.socket is not None)
        await socket.notify(event, **body)
        await until(lambda: call.closed)
        await asyncio.gather(call.task, return_exceptions=True)
        assert states[-1] == expected and socket.closed
    ok("remote cancellation and unsupported topology clean up")


async def backend_dial():
    from fake_link import FakeLink
    fake = FakeLink(can={"calls"})
    fake.person(10, "Тестовый собеседник")
    dialog = fake.dialog(10)
    group = fake.group(20, "Тестовая группа")
    class UI:
        def call_changed(self, state):
            return False
    backend = bm.Backend(UI(), fake)
    account = backend.accounts["max"]
    account.online, account.me, account.chats = True, fake.me.id, fake.rooms
    gate = asyncio.Event()
    requests = []
    async def dial(conversation, person):
        requests.append(person)
        await gate.wait()
        return dict(params)
    fake.dial = dial
    pending = asyncio.create_task(backend.call("dial", peer=dialog))
    await until(lambda: account.call is not None)
    old = account.call
    socket = Socket()
    old.connect = lambda *args, **kwargs: socket
    await backend.call("dial", peer=dialog)
    assert requests == [10]  # another tap while dialling cannot send opcode 78 again
    await backend.call("end", conversation=old.id)
    assert account.call is None
    gate.set()
    await pending
    await old.task
    assert socket.commands() == ["hangup"] and socket.sent[0]["reason"] == "CANCELED"
    for peer in (group, 999):
        try:
            await backend.call("dial", peer=peer)
        except ValueError:
            pass
        else:
            raise AssertionError("called a group or unknown dialog")
    account.online = False
    try:
        await backend.call("dial", peer=dialog)
    except bm.Offline:
        pass
    else:
        raise AssertionError("called while offline")
    assert requests == [10]
    ok("one dial per tap, dialog/account guards and cancellation before opcode 78 replies")


async def main():
    await scenario(True)
    await scenario(False)
    await rejection()
    await cancelled_before_connect()
    await terminal_events()
    await backend_dial()


asyncio.run(main())
