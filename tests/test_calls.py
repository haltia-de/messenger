# SPDX-License-Identifier: GPL-3.0-or-later
"""Calls on a fake signalling service: no account, network or microphone."""
import asyncio
import base64
import json
import threading
from unittest.mock import AsyncMock, Mock, patch
from types import SimpleNamespace
from common import load, ok

bm = load()


def media_probe():
    for missing in ("Gst", "GstWebRTC", "GstSdp"):
        bm.calls_supported.cache_clear()
        def require_namespace(namespace, version):
            if namespace == missing:
                raise ValueError("missing typelib")
        try:
            with patch.object(bm.gi, "require_version", side_effect=require_namespace) as require:
                first = bm.PyMaxLink("unused")
                second = bm.PyMaxLink("unused")
                assert "calls" not in first.can and "calls" not in second.can
                assert "phone" in first.can
                assert require.call_count == ("Gst", "GstWebRTC", "GstSdp").index(missing) + 1
        finally:
            bm.calls_supported.cache_clear()
    for missing in ("webrtcbin", "opusenc", "nicesrc", "pulsesrc", None):
        bm.calls_supported.cache_clear()
        gst = SimpleNamespace(init=Mock(), ElementFactory=SimpleNamespace(
            find=Mock(side_effect=lambda name: None if name == missing else object())))
        try:
            with patch.object(bm, "call_media", return_value=(gst, object(), object())) as load_media:
                first = bm.PyMaxLink("unused")
                second = bm.PyMaxLink("unused")
                assert ("calls" in first.can) == (missing is None)
                assert first.can == second.can and load_media.call_count == 1
                gst.init.assert_called_once_with(None)
        finally:
            bm.calls_supported.cache_clear()
    ok("missing media disables calls; positive and negative probes run only once")


media_probe()


# A missing video plugin must not withdraw working audio calls.
for missing in ("vp8enc", "vp8dec", "appsink", None):
    bm.video_supported.cache_clear()
    gst = SimpleNamespace(init=Mock(), ElementFactory=SimpleNamespace(
        find=Mock(side_effect=lambda name: None if name == missing else object())))
    with patch.object(bm, "call_media", return_value=(gst, object(), object())) as probe:
        assert bm.video_supported() == (missing is None)
        assert bm.video_supported() == (missing is None)
        assert probe.call_count == 1
    bm.video_supported.cache_clear()
ok("video support is probed once independently of voice support")


def camera_refresh():
    import haltia_kit
    # A stale discovery, link or startup must be replaced, never reused.
    for failure in ("missing", "link", "state", "persistent", "link-twice", "state-twice", "raw-fallback"):
        peers = []
        for n in range(2):
            source = Mock()
            source.get_factory.return_value.get_name.return_value = (
                "v4l2src" if failure == "raw-fallback" and n else "libcamerasrc")
            source.link_filtered.return_value = not (failure == "link-twice" or
                (n == 0 and failure in ("link", "raw-fallback")))
            peers.append(SimpleNamespace(front=True, make=Mock(return_value=source)))
        discoveries = [[], [peers[1]]] if failure == "missing" else [[peers[0]], [peers[1]]]
        if failure == "persistent":
            discoveries = [[], []]
        camera_module = SimpleNamespace(cameras=Mock(side_effect=discoveries))
        pipelines = []
        scheduled, statuses = [], []
        audio = bm.CallAudio.__new__(bm.CallAudio)
        audio.camera, audio.closed, audio.video_generation = None, False, 0
        audio.video_bin, audio.video_size = object(), (320, 240, 15)
        audio.loop = SimpleNamespace(call_soon_threadsafe=lambda cb, *a: scheduled.append((cb,a)))
        audio.status = statuses.append
        def pipeline(*_args):
            pipe = Mock()
            index = len(pipelines)
            def state(value):
                if value == "playing" and (failure == "state-twice" or (index == 0 and failure == "state")):
                    audio._camera_bus(pipe.get_bus(), SimpleNamespace(type="error"), None)
                    return "failure"
                return "success"
            pipe.set_state.side_effect = state
            pipelines.append(pipe)
            return pipe
        audio.Gst = SimpleNamespace(
            State=SimpleNamespace(NULL="null", PLAYING="playing"),
            StateChangeReturn=SimpleNamespace(FAILURE="failure"),
            MessageType=SimpleNamespace(ERROR="error"), BusSyncReply=SimpleNamespace(DROP="drop"),
            Caps=SimpleNamespace(from_string=lambda text: text), parse_launch=pipeline)
        with patch.dict(bm.os.environ, {"HALTIA_CAMERA_SOURCE": ""}), \
                patch.object(haltia_kit, "camera", camera_module, create=True):
            if failure in ("persistent", "link-twice", "state-twice", "raw-fallback"):
                try:
                    audio.set_video(True)
                except RuntimeError:
                    pass
                else:
                    raise AssertionError("failed camera unexpectedly opened")
                assert audio.camera is None
            else:
                assert audio.set_video(True) is True
                assert audio.camera is pipelines[-1]
                # A queued error from the discarded source cannot stop the new one.
                for cb, args in scheduled:
                    cb(*args)
                assert not statuses
            assert camera_module.cameras.call_count == 2
            for pipe in pipelines[:-1] if audio.camera is not None else pipelines:
                assert any(c.args == ("null",) for c in pipe.set_state.call_args_list)
            audio.set_video(False)
            assert audio.camera is None and not audio.closed
    ok("stale camera discovery/link/start retries once with fresh elements; no raw Bayer fallback")


camera_refresh()


def bus_errors():
    # An error inside the video branches stops video only; any other ends the
    # call. The log names the element and the code, never the debug text.
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
    Gst.init(None)
    audio = bm.CallAudio.__new__(bm.CallAudio)
    audio.Gst, audio.closed, audio.failed_bins = Gst, False, []
    audio.video_bin, audio.remote_bin = Gst.Bin.new("send"), Gst.Bin.new("receive")
    encoder, decoder = Gst.ElementFactory.make("identity", None), Gst.ElementFactory.make("queue", None)
    audio.video_bin.add(encoder)
    audio.remote_bin.add(decoder)
    other = Gst.ElementFactory.make("fakesink", None)
    statuses, lines = [], []
    audio.status = statuses.append
    audio.loop = SimpleNamespace(call_soon_threadsafe=lambda cb, *a: cb(*a))
    error = bm.GLib.Error.new_literal(Gst.StreamError.quark(), "turn:secret@host", 1)
    with patch.object(bm, "log_line", side_effect=lines.append):
        for src in (encoder, decoder, other):
            audio._bus(None, SimpleNamespace(type=Gst.MessageType.ERROR, src=src,
                                             parse_error=lambda: (error, "turn:secret@host")), None)
    assert statuses == ["send-video-failed", "remote-video-failed", "failed"], statuses
    assert "identity" in lines[0] and "fakesink" in lines[2] and not any("secret" in l for l in lines)
    # One failure posts several errors, all classified while the branch is in
    # use; on the loop, those of a branch replaced meanwhile (or of the peer's,
    # given up) count no more.
    statuses.clear()
    queued = []
    audio.loop = SimpleNamespace(call_soon_threadsafe=lambda cb, *a: queued.append((cb, a)))
    audio.video_bin, audio.remote_bin = Gst.Bin.new("send"), Gst.Bin.new("receive")
    encoder, decoder = Gst.ElementFactory.make("identity", None), Gst.ElementFactory.make("queue", None)
    audio.video_bin.add(encoder)
    audio.remote_bin.add(decoder)
    with patch.object(bm, "log_line"):
        for src in (encoder, encoder, decoder, decoder):
            audio._bus(None, SimpleNamespace(type=Gst.MessageType.ERROR, src=src,
                                             parse_error=lambda: (error, "")), None)
        for k, (cb, args) in enumerate(queued):
            cb(*args)
            if statuses == ["send-video-failed"] and k < 3:
                audio.video_bin = Gst.Bin.new("rebuilt")  # as rebuild_sender does
    assert statuses == ["send-video-failed", "remote-video-failed"], statuses
    # Errors arriving after the loop gave a branch up: never the call's
    statuses.clear()
    queued.clear()
    with patch.object(bm, "log_line"):
        for src in (decoder, encoder):  # the peer's failed branch; the sender replaced
            audio._bus(None, SimpleNamespace(type=Gst.MessageType.ERROR, src=src,
                                             parse_error=lambda: (error, "")), None)
        for cb, args in queued:
            cb(*args)
    assert statuses == [], statuses
    ok("video branch errors stop video only; logged by element and code without the debug text")


bus_errors()


def sender_rebuilt():
    # A failed sending branch is replaced in place: same payload, same pad.
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
    Gst.init(None)
    if Gst.ElementFactory.find("vp8enc") is None:
        ok("video sender rebuild skipped: no vp8enc here")
        return
    audio = bm.CallAudio.__new__(bm.CallAudio)
    audio.Gst, audio.closed, audio.failed_bins = Gst, False, []
    audio.pipeline = Gst.Pipeline.new("call")
    sink = Gst.ElementFactory.make("fakesink", None)
    audio.pipeline.add(sink)
    audio.video_pad = sink.get_static_pad("sink")
    audio.video_bin = audio._sender_bin(102)
    audio.pipeline.add(audio.video_bin)
    audio.video_bin.get_static_pad("src").link(audio.video_pad)
    old = audio.video_bin
    assert audio.rebuild_sender()
    assert audio.video_bin is not old and old.get_parent() is None
    assert audio.video_bin.get_by_name("video_pay").get_property("pt") == 102
    assert audio.video_bin.get_static_pad("src").get_peer() == audio.video_pad
    audio.closed = True
    assert not audio.rebuild_sender()
    audio.pipeline.set_state(Gst.State.NULL)
    ok("a failed video sender is rebuilt on the same pad with the same payload")


sender_rebuilt()


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


async def unavailable_media():
    from fake_link import FakeLink
    fake = FakeLink(can={"phone"})
    backend = bm.Backend(object(), fake)
    account = backend.accounts["max"]
    account.online = True
    with patch.object(bm, "call_params", side_effect=AssertionError("invitation was parsed")):
        await account.on_call_frame(137, {"vcp": "unavailable"})
    assert account.call is None
    try:
        await backend.call("dial", peer=10)
    except bm.Offline:
        pass
    else:
        raise AssertionError("dialled without media support")
    ok("no media capability: invitations ignored and outgoing calls blocked")


async def connection_states():
    def make():
        call = bm.VoiceCall("network", "test-person", False, lambda *args: None)
        assert 5 <= call.DISCONNECT_GRACE <= 10
        call.DISCONNECT_GRACE = .03
        call.audio = Audio(None, None, call.audio_state, {})
        call.audio_state("connected")
        return call
    call = make()
    call.audio_state("closed")
    await asyncio.sleep(.01)
    assert not call.closed
    call.audio_state("disconnected")
    await asyncio.sleep(.01)
    assert not call.closed and not call.audio.closed
    call.audio_state("connected")
    await asyncio.sleep(.06)
    assert not call.closed and call.state == "active"
    await call.end()
    call = make()
    call.audio_state("disconnected")
    await until(lambda: call.closed)
    assert call.end_reason == "NETWORK_ERROR" and call.audio.closed
    call = make()
    call.audio_state("failed")
    await until(lambda: call.closed)
    assert call.state == "failed" and call.audio.closed
    call = make()
    call.audio_state("disconnected")
    await call.end("HUNGUP")
    await asyncio.sleep(.06)
    assert call.end_reason == "HUNGUP"  # no late network timeout after hangup
    ok("disconnected grace, recovery, persistent failure and timeout cancellation")


async def stop_reasons():
    from fake_link import FakeLink
    for incoming, accepted, reason in ((True, False, "REJECTED"),
                                        (False, False, "CANCELED"),
                                        (True, True, "HUNGUP"), (False, True, "HUNGUP")):
        account = bm.Backend(object(), FakeLink()).accounts["max"]
        call = bm.VoiceCall("stop", "test-person", incoming, lambda *args: None)
        call.accepted = accepted
        account.call = call
        await account.stop()
        assert call.closed and call.end_reason == reason
    ok("account stop rejects incoming, cancels outgoing and hangs up accepted calls")


async def busy_invitation():
    from fake_link import FakeLink
    fake = FakeLink(can={"calls"})
    account = bm.Backend(object(), fake).accounts["max"]
    account.online = True
    primary = account.call = bm.VoiceCall("primary", 10, True, lambda *_args: None)
    primary.accepted = True
    primary.state = "active"
    made = len(Audio.made)
    connected = asyncio.Event()
    class BusySocket(Socket):
        async def __aenter__(self):
            await connected.wait()
            return await super().__aenter__()
    socket = BusySocket()
    real_call = bm.VoiceCall
    def other(*args, **kwargs):
        return real_call(*args, **kwargs, audio=Audio, connect=lambda *_args, **_kwargs: socket)
    with patch.object(bm, "VoiceCall", side_effect=other) as factory:
        invitation = {"conversationId": "second", "callerId": 20, "vcp": literal(params)}
        await account.on_call_frame(137, dict(invitation, conversationId="primary"))
        assert factory.call_count == 0  # a duplicate of the current call must not reject it
        pending = asyncio.create_task(account.on_call_frame(137, invitation))
        await until(lambda: factory.call_count == 1)
        await account.on_call_frame(137, invitation)  # duplicate during the pending handshake
        assert factory.call_count == 1
        connected.set()
        await pending
    assert account.call is primary and not primary.closed and primary.state == "active"
    assert len(Audio.made) == made
    assert socket.commands() == ["hangup"] and socket.sent[0]["reason"] == "BUSY"
    assert socket.closed and not account.declining
    await account.on_call_frame(121, {"conversationId": "second"})
    assert not primary.closed
    await primary.end()
    ok("second invitation gets BUSY without media, UI changes or ending the current call")


async def quit_hangup():
    from fake_link import FakeLink
    backend = bm.Backend(object(), FakeLink())
    account = backend.accounts["max"]
    sent = asyncio.Event()
    class DelayedSocket(Socket):
        async def send(self, raw):
            await asyncio.sleep(.03)
            await super().send(raw)
            sent.set()
    socket = DelayedSocket()
    call = account.call = bm.VoiceCall("quit", 10, False, lambda *_args: None)
    call.accepted = True
    call.audio = Audio(None, None, call.audio_state, {})
    call.socket = socket
    ending = asyncio.create_task(backend.hangup_calls())
    await asyncio.sleep(.01)
    assert not ending.done() and call.audio.closed
    await ending
    assert sent.is_set() and socket.closed and socket.sent[0]["reason"] == "HUNGUP"
    ok("quit waits for a delayed hangup send and releases media first")


async def quit_during_dial(fails=False):
    from fake_link import FakeLink
    fake = FakeLink(can={"calls"})
    fake.person(10, "Тестовый собеседник")
    dialog = fake.dialog(10)
    class UI:
        def call_changed(self, state):
            return False
    backend = bm.Backend(UI(), fake)
    account = backend.accounts["max"]
    account.online, account.me, account.chats = True, fake.me.id, fake.rooms
    gate = asyncio.Event()
    async def dial(*_args):
        await gate.wait()
        if fails:
            raise bm.Offline()
        return dict(params)
    fake.dial = dial
    pending = asyncio.create_task(backend.call("dial", peer=dialog))
    await until(lambda: account.call is not None)
    call = account.call
    socket = Socket()
    call.connect = lambda *_args, **_kwargs: socket
    ending = asyncio.create_task(backend.hangup_calls())
    await asyncio.sleep(.01)
    assert not ending.done() and call.closed
    gate.set()
    if fails:
        try:
            await pending
        except bm.Offline:
            pass
        else:
            raise AssertionError("dial should fail")
        await asyncio.wait_for(ending, .2)
        assert call.hangup_done.is_set() and call.task is None
        ok("failed setup releases the quit waiter without the two-second timeout")
        return
    await pending
    await asyncio.wait_for(ending, 1)
    await call.task
    assert socket.commands() == ["hangup"] and socket.sent[0]["reason"] == "CANCELED"
    ok("quit waits for cancellation while outgoing setup is still pending")


async def missed_calls():
    from fake_link import FakeLink
    notices, states = [], {}
    class UI:
        def call_changed(self, call):
            states.setdefault(call["id"], []).append(call["state"])
            return False
        def missed_call(self, notice):
            notices.append(notice)
            return False
    fake = FakeLink(can={"calls"})
    account = bm.Backend(UI(), fake).accounts["max"]
    account.me = fake.me.id
    account.names[10] = "Тестовый собеседник"
    class Broken(Audio):
        def close(self):
            raise RuntimeError("synthetic teardown failure")
    cases = ("remote", "timeout", "declined", "answered", "outgoing", "elsewhere", "stopped", "broken")
    for video, case in ((v, c) for v in (False, True) for c in cases):
        call = account.new_call(case, 10, case != "outgoing", video=video)
        if case == "broken":
            call.audio = Broken(None, None, None, None)
            try:
                await call.end("REJECTED")
            except RuntimeError:
                pass
        elif case == "stopped":
            await account.stop()
        elif case == "remote":
            await account.on_call_frame(121, {"conversationId": case})
            await account.on_call_frame(121, {"conversationId": case})
        elif case == "elsewhere":
            await account.on_call_frame(120, {"conversationId": case})
        else:
            call.accepted = case == "answered"
            await call.end("REJECTED" if case == "declined" else "MISSED" if case == "timeout" else None)
        await call.end()  # A duplicate closure cannot create another notice.
        while bm.GLib.MainContext.default().iteration(False):
            pass
        # Every way a call ends tells the window (which closes the ringing
        # call's notification on it), for voice and video invitations alike.
        assert states.pop(case)[-1] in ("ended", "failed"), case
    assert [n["id"] for n in notices] == ["remote", "timeout"] * 2
    assert all(n["chat"] == fake.dialog_of(fake.me.id, 10) and n["peer"] == 10
               and n["name"] == "Тестовый собеседник" and n["time"] > 0 for n in notices)
    ok("every end tells the window, even a failed teardown; unanswered closure and timeout are missed, not decline, answer, outgoing, answer elsewhere or stop")


async def video_dial_flag():
    link = bm.PyMaxLink.__new__(bm.PyMaxLink)
    invoke = AsyncMock(return_value=SimpleNamespace(payload={"internalCallerParams": "{}"}))
    link.client = SimpleNamespace(_app=SimpleNamespace(
        session=SimpleNamespace(device_id="synthetic-device"), invoke=invoke))
    for video in (False, True):
        assert await link.dial("synthetic-conversation", 10, video=video) == {}
        opcode, payload = invoke.call_args.args
        assert opcode == 78 and payload["isVideo"] is video
        assert payload["calleeIds"] == [10]
    ok("video selection reaches opcode 78; voice retains isVideo=false")


async def video_consent():
    class VideoAudio(Audio):
        def __init__(self, *args):
            super().__init__(*args)
            self.video_size = (320, 240, 15)
            self.camera = False
            self.fail = False
            self.hold = None
            self.threads = set()
            self.asked = []  # set_video's calls, in order
            self.sdp_first = None  # was the SDP out when the camera was asked to open
        def set_video(self, enabled):
            self.threads.add(threading.current_thread().name)
            self.asked.append(bool(enabled))
            if enabled and self.sdp_first is None:
                self.sdp_first = "transmit-data" in self.sent()
            if enabled and self.hold:
                opened, release = self.hold
                self.hold = None
                opened.set()
                release.wait(5)
            self.camera = False
            if self.closed:
                return False  # hung up while it opened: never left on
            if enabled and self.fail:
                raise RuntimeError("synthetic busy camera")
            self.camera = bool(enabled)
            return self.camera
        def close(self):
            self.camera = False
            super().close()
    for answer_video in (True, False):
        shown = []
        socket = Socket()
        call = bm.VoiceCall("video-consent", "test-person", True, lambda c, _s: shown.append(c.video),
                            audio=VideoAudio, connect=lambda *_a, **_k: socket, video=True)
        VideoAudio.sent = lambda _self, socket=socket: socket.commands()
        task = asyncio.create_task(call.run(dict(params)))
        await until(lambda: "change-participant-state" in socket.commands())
        assert call.audio is None and not call.video
        initial = next(v for v in socket.sent if isinstance(v, dict) and v["command"] == "change-media-settings")
        assert not initial["mediaSettings"]["isVideoEnabled"]
        await socket.notify("transmitted-data", participantId="remote", data={
            "sdp": {"type": "offer", "sdp": "synthetic"}})
        call.job(call.answer(video=answer_video))
        await until(lambda: call.audio is not None and "transmit-data" in socket.commands()
                    and call.audio.camera == answer_video)
        assert call.video == answer_video and call.video_wanted == answer_video
        # The SDP goes first: ICE does not wait for the camera to open.
        assert call.audio.sdp_first in ((True,) if answer_video else (None,))
        accepted = next(v for v in socket.sent if isinstance(v, dict) and v["command"] == "accept-call")
        assert accepted["mediaSettings"]["isVideoEnabled"] == answer_video
        call.audio_state("connected")
        # The microphone off: the peer is told, the call goes on
        call.toggle_mute()
        await until(lambda: any(isinstance(v, dict) and v.get("command") == "change-media-settings"
                                and v["mediaSettings"]["isAudioEnabled"] is False for v in socket.sent))
        assert call.muted and shown[-1] == call.video and not call.closed
        call.toggle_mute()
        assert not call.muted and call.media_settings()["isAudioEnabled"]
        assert call.since is not None  # the talk's start, for its time on the screen

        async def switch(on):
            if call.video_wanted != on:
                call.toggle_camera()
            await until(lambda: call.video == on and call.audio.camera == on)
        await switch(False)
        gate = asyncio.Event()
        async def slow_ack(*_args, **_kwargs):
            await gate.wait()
        with patch.object(call, "command", side_effect=slow_ack):
            call.toggle_camera()
            await until(lambda: call.audio.camera)
            assert shown[-1] is True  # the own picture before the slow acknowledgement
            gate.set()
            await asyncio.sleep(0)
        # A refused acknowledgement of a camera switch never ends the call.
        async def refused(*_args, **_kwargs):
            raise RuntimeError("synthetic refusal")
        with patch.object(call, "command", side_effect=refused):
            await switch(False)
            await switch(True)
        assert not call.closed and call.state == "active"
        # A dim room slows the camera: no overload while the encoder keeps up.
        await call.adapt_video(8, 9)
        assert call.audio.video_size == (320, 240, 15) and call.video
        await call.adapt_video(3, 15)
        assert call.audio.video_size == (160,120,10) and call.video
        await call.adapt_video(3, 15)
        assert not call.video and not call.audio.camera and call.state == "active"
        assert not call.video_wanted  # turned off: adaptation never turns it on again
        await call.adapt_video(0, 15)
        assert not call.video
        call.audio.fail = True
        call.toggle_camera()
        await until(lambda: call.video_error and not call.video_wanted)
        assert not call.video and not call.audio.camera and not call.closed
        # The peer's picture failing leaves the own camera on; the sender
        # failing is built anew once, then video stops; never the call.
        call.audio.fail = False
        await switch(True)
        call.audio_state("remote-video-failed")
        await asyncio.sleep(.05)
        assert call.video and call.audio.camera and call.remote_video is False
        call.audio.rebuilt = 0
        call.audio.rebuild_sender = lambda: setattr(call.audio, "rebuilt", call.audio.rebuilt + 1) or True
        call.audio_state("send-video-failed")
        await asyncio.sleep(.05)
        assert call.audio.rebuilt == 1 and call.video and call.audio.camera
        call.audio_state("send-video-failed")
        await until(lambda: not call.video)
        assert call.audio.rebuilt == 1
        assert not call.closed and call.state == "active" and call.video_error
        await socket.notify("media-settings-changed", participantId="remote", mediaSettings={"isVideoEnabled": True})
        await until(lambda: call.remote_video is True)
        assert not call.video  # A peer cannot turn our camera on.
        # Opening the camera blocks its own thread, never the loop; two quick
        # taps are folded: on, then off, and it ends off.
        opened, release = threading.Event(), threading.Event()
        call.audio.hold = (opened, release)
        call.audio.asked.clear()
        call.toggle_camera()
        await until(opened.is_set)
        call.toggle_camera()
        await asyncio.sleep(.05)
        assert not call.video and not call.video_wanted
        release.set()
        await until(lambda: call.audio.asked == [True, False] and not call.audio.camera)
        assert not call.video and call.audio.threads == {"camera"}
        # Hanging up while a camera opens: the loop answers at once, and the
        # camera is not left on when it finishes opening.
        opened, release = threading.Event(), threading.Event()
        call.audio.hold = (opened, release)
        call.toggle_camera()
        await until(opened.is_set)
        loop = asyncio.get_running_loop()
        began = loop.time()
        await asyncio.wait_for(call.end("HUNGUP"), 1)
        assert loop.time() - began < .5 and opened.is_set() and not release.is_set()
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(.1)
        assert call.audio.closed and not call.audio.camera
    ok("video consent, SDP before the camera, folded taps, hang-up while a camera opens, non-fatal acks and video errors, dim light, overload downgrade and peer isolation")


async def end_logging():
    for remote in (False, True):
        for reason in ("HUNGUP", "REJECTED", "CANCELED", "BUSY", "MISSED", "NETWORK_ERROR", "FAILED"):
            call = bm.VoiceCall("private-conversation", "private-person", True, lambda *_a: None)
            with patch.object(bm, "log_line") as log:
                if remote:
                    await call.event({"notification": "hungup", "reason": reason})
                    assert call.end_reason is None  # Do not echo a remote hangup.
                else:
                    await call.end(reason)
                    assert call.end_reason == reason
                await call.end()  # Finally/duplicate frames cannot overwrite the reason.
                label = "failed" if reason == "FAILED" else reason
                log.assert_called_once_with("voice call: ended reason=%s by=%s state=ended" %
                                            (label, "remote" if remote else "local"))
    for reason in (None, "private-token\nHUNGUP", {"id": "private"}, ["HUNGUP"]):
        call = bm.VoiceCall("private-conversation", "private-person", True, lambda *_a: None)
        with patch.object(bm, "log_line") as log:
            await call.event({"notification": "closed-conversation", "reason": reason})
            log.assert_called_once_with("voice call: ended reason=unknown by=remote state=ended")
    call = bm.VoiceCall("private-conversation", "private-person", False, lambda *_a: None)
    with patch.object(bm, "log_line") as log:
        await call.end(None, "failed")
        log.assert_called_once_with("voice call: ended reason=failed by=local state=failed")
    ok("terminal logs contain only allowed reasons and local/remote origin, once, without identifiers")


async def main():
    await end_logging()
    await video_dial_flag()
    await video_consent()
    await scenario(True)
    await scenario(False)
    await rejection()
    await cancelled_before_connect()
    await terminal_events()
    await backend_dial()
    await unavailable_media()
    await connection_states()
    await stop_reasons()
    await busy_invitation()
    await quit_hangup()
    await quit_during_dial()
    await quit_during_dial(fails=True)
    await missed_calls()


asyncio.run(main())
