# SPDX-License-Identifier: GPL-3.0-or-later
"""Calls on a fake signalling service: no account, network or microphone."""
import asyncio
import base64
import concurrent.futures
import json
import threading
import time
from unittest.mock import AsyncMock, Mock, patch
from types import SimpleNamespace
from common import load, ok

bm = load()
bm.SETTINGS.set("calls_video", True)  # «Видеозвонки» on here (off by default, #55); voice-only below


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
            peers.append(SimpleNamespace(front=True, make=lambda source=source: source))  # kit 2.3.0: no size
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
                    audio._camera_bus(pipe.get_bus(), SimpleNamespace(
                        type="error", src=None, parse_error=lambda: (SimpleNamespace(domain="x", code=1), "")), None)
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


def turned_camera():
    import time
    # haltia-kit 2.4's Camera.make() gives a bin (the source, then a videoflip
    # turning the picture with the screen): its source is found inside it, and
    # a tablet held upright sends an upright picture, not a squashed one.
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
    import haltia_kit
    Gst.init(None)
    asked = []
    def make(caps=None):  # haltia-kit 2.3.1: the size asked before the turn
        asked.append(caps)
        box = Gst.Bin.new(None)
        src = Gst.ElementFactory.make("videotestsrc", None)
        src.set_property("is-live", True)
        flip = Gst.ElementFactory.make("videoflip", "turn")
        Gst.util_set_object_arg(flip, "video-direction", "90r")
        box.add(src)
        box.add(flip)
        src.link_filtered(flip, Gst.Caps.from_string("video/x-raw,width=480,height=360"))
        box.add_pad(Gst.GhostPad.new("src", flip.get_static_pad("src")))
        return box
    audio = bm.CallAudio.__new__(bm.CallAudio)
    audio.Gst, audio.closed, audio.camera, audio.video_generation = Gst, False, None, 0
    audio.video_bin, audio.video_size, audio.failed_bins = None, (480, 360, 15), []
    audio.loop = SimpleNamespace(call_soon_threadsafe=lambda cb, *a: None)
    sizes = []
    def sample(sink, own, generation):
        got = sink.emit("pull-sample")
        caps = got.get_caps().get_structure(0)
        sizes.append((caps.get_value("width"), caps.get_value("height")))
        return Gst.FlowReturn.OK
    audio._frame_sample = sample
    audio._send_video = lambda sink, generation: (sample(sink, False, 0), Gst.FlowReturn.OK)[1]
    cam = SimpleNamespace(front=True, make=make)
    with patch.dict(bm.os.environ, {"HALTIA_CAMERA_SOURCE": ""}), \
            patch.object(haltia_kit, "camera", SimpleNamespace(cameras=lambda: [cam]), create=True):
        assert audio._source_of(make()).get_factory().get_name() == "videotestsrc"
        audio.video_bin = object()  # no encoder here: the bitrate is not set
        assert audio._start_camera(None)
        assert audio.camera_kind == "videotestsrc"
        deadline = time.monotonic() + 5
        while len(sizes) < 4 and time.monotonic() < deadline:
            time.sleep(.05)
        audio.camera.set_state(Gst.State.NULL)
    assert sizes and all(h > w for w, h in sizes), sizes  # upright, as turned
    assert asked[-1] == "video/x-raw,width=480,height=360" and audio.sized
    # haltia-kit 2.3.0's make() takes no size: the plain source, sized by the call
    old = SimpleNamespace(front=True, make=lambda: make())
    with patch.dict(bm.os.environ, {"HALTIA_CAMERA_SOURCE": ""}), \
            patch.object(haltia_kit, "camera", SimpleNamespace(cameras=lambda: [old]), create=True):
        assert audio._start_camera(None) and not audio.sized
        audio.camera.set_state(Gst.State.NULL)
    ok("a camera turned with the screen: its source found inside, its picture upright")


turned_camera()


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
    audio.video_size = (640, 480, 15)
    sink = Gst.ElementFactory.make("fakesink", None)
    audio.pipeline.add(sink)
    audio.video_pad = sink.get_static_pad("sink")
    audio.video_bin = audio._sender_bin(102)
    audio.pipeline.add(audio.video_bin)
    audio.video_bin.get_static_pad("src").link(audio.video_pad)
    old = audio.video_bin

    async def rebuild():
        assert await audio.rebuild_sender()
        assert audio.video_bin is not old and old.get_parent() is None
        assert audio.video_bin.get_by_name("video_pay").get_property("pt") == 102
        assert audio.video_bin.get_by_name("video_encoder").get_property("target-bitrate") == \
            bm.VIDEO_BITRATE[audio.video_size[0]]  # not vp8enc's default
        assert audio.video_bin.get_static_pad("src").get_peer() == audio.video_pad
        audio.closed = True
        assert not await audio.rebuild_sender()
        audio.pipeline.set_state(Gst.State.NULL)

    asyncio.run(rebuild())
    ok("a failed video sender is rebuilt on the same pad with the same payload")


sender_rebuilt()


def stand_in_audio(pipeline):
    """A CallAudio as the call holds it, on a stand-in pipeline."""
    audio = bm.CallAudio.__new__(bm.CallAudio)
    audio.Gst = SimpleNamespace(State=SimpleNamespace(NULL="null", PLAYING="playing"),
                                StateChangeReturn=SimpleNamespace(FAILURE="failure"),
                                PadDirection=SimpleNamespace(SRC="src"),
                                PadLinkReturn=SimpleNamespace(OK="ok"),
                                Caps=SimpleNamespace(from_string=lambda text: text))
    audio.closed, audio.video_generation, audio.media_generation, audio.camera = False, 0, 0, None
    audio.sender_generation, audio.sender_lock = 0, None
    audio.frame = audio.video_bin = audio.video_pad = audio.rtc = audio.bus = None
    audio.signals, audio.pending, audio.failed_bins = [], [], []
    audio.candidate = audio.status = lambda _value: None
    audio.sink, audio.video_ok, audio.remote_bin = "fakesink", True, None
    audio.video_size = (320, 240, 15)
    audio.pipeline = pipeline
    return audio


class StoppingPipeline:
    """Stops its children with itself, as a Gst.Bin does."""
    def __init__(self, release=None):
        self.state, self.children, self.release = "playing", [], release
        self.stopping = threading.Event()
    def add(self, element):
        self.children.append(element)
    def set_state(self, state):
        self.stopping.set()
        if self.release is not None:
            self.release.wait(5)  # the microphone's and libnice's threads stopping
        self.state = state
        for child in self.children:
            child.set_state(state)
        return "success"


class DelayedState:
    """A Gst element stand-in: set_state waits until release is set."""

    def __init__(self, release, order=None, name="el"):
        self.release, self.order, self.name = release, order if order is not None else [], name
        self.states, self.started, self.fail = [], threading.Event(), False

    def set_state(self, state):
        self.started.set()
        assert self.release.wait(5)
        if self.fail:
            return "failure"
        self.states.append(state)
        self.order.append((self.name, state))
        return "success"


class FakeBin:
    """A video sender stand-in for rebuild_sender/remote without GStreamer."""

    def __init__(self, delayed=None, pt=96):
        self.delayed, self.pt, self.synced, self.caps = delayed, pt, False, None
        self.encoder_rate = None

    def set_state(self, state):
        return self.delayed.set_state(state) if self.delayed is not None else "success"

    def get_by_name(self, name):
        if name == "video_pay":
            return SimpleNamespace(get_property=lambda _p: self.pt,
                                   set_property=lambda _k, value: setattr(self, "pt", value))
        if name == "video_encoder":
            return SimpleNamespace(set_property=lambda _k, value: setattr(self, "encoder_rate", value))
        if name == "video_caps":
            return SimpleNamespace(set_property=lambda _k, value: setattr(self, "caps", value))
        return None

    def get_static_pad(self, _name):
        return SimpleNamespace(unlink=lambda _pad: None, link=lambda _pad: "ok")

    def sync_state_with_parent(self):
        self.synced = True


def media_teardown():
    # MSG2-12 (#84): hanging up stopped the pipeline on the asyncio loop,
    # which waited for every streaming thread. Now MEDIA_WORKER does.
    import time
    release = threading.Event()
    pipeline = StoppingPipeline(release)
    audio = stand_in_audio(pipeline)
    began = time.monotonic()
    audio.close()
    assert time.monotonic() - began < 1, "close() waited for the pipeline"
    assert pipeline.stopping.wait(5) and pipeline.state == "playing"  # still stopping
    assert audio.closed and audio.pipeline is None
    stopped = audio.stopped
    audio.close()  # idempotent: stopped once
    assert audio.stopped is stopped
    release.set()
    assert stopped.result(5) == "success" and pipeline.state == "null"
    ok("a call's pipeline stops on its own worker, never on the loop")

    # MSG2-13 (#84): a peer's stream added by its streaming thread while the
    # loop hangs up. The bin read its parent's PLAYING, then the pipeline
    # stopped before the bin followed: it was left playing in a dead call.
    pipeline = StoppingPipeline()
    audio = stand_in_audio(pipeline)
    audio._phone_streams = lambda _bin: None

    class Received:
        state = "null"
        def get_static_pad(self, _name):
            return "sink"
        def sync_state_with_parent(self):
            seen = pipeline.state
            audio.close()  # on the loop, meanwhile
            deadline = time.monotonic() + 5
            while pipeline.state != "null" and time.monotonic() < deadline:
                time.sleep(.01)
            self.state = seen
        def set_state(self, state):
            self.state = state
    received = Received()
    audio.Gst.parse_bin_from_description = lambda _description, _ghost: received
    structure = SimpleNamespace(get_string=lambda _field: "audio")
    caps = SimpleNamespace(get_structure=lambda _n: structure)
    linked = []
    pad = SimpleNamespace(direction="src", get_current_caps=lambda: caps, link=linked.append)
    audio._received(None, pad)
    assert received in pipeline.children and linked == ["sink"]
    assert pipeline.state == "null" and received.state == "null", received.state
    # Once closed, a stream coming late is not added at all.
    late = Received()
    audio.Gst.parse_bin_from_description = lambda _description, _ghost: late
    audio._received(None, pad)
    assert late not in pipeline.children and late.state == "null"
    ok("a peer's stream added while the call closes is stopped with it")


media_teardown()


def media_wait_shutdown():
    # Bounded shutdown closes the asyncio loop while MEDIA_WORKER may still
    # finish a job; the done-callback must not log RuntimeError.
    import logging
    loop = asyncio.new_event_loop()
    job = concurrent.futures.Future()

    async def begin():
        return bm.media_wait(job)

    waiter = loop.run_until_complete(begin())
    loop.close()
    with patch.object(logging.getLogger("concurrent.futures"), "exception") as logged:
        job.set_result("ok")
        assert not logged.called, logged.call_args_list
    assert not waiter.done()
    ok("media_wait after the loop closes does not log RuntimeError")

    async def propagates():
        failed = concurrent.futures.Future()
        waiting = bm.media_wait(failed)
        failed.set_exception(RuntimeError("synthetic media"))
        try:
            await waiting
        except RuntimeError as exc:
            assert str(exc) == "synthetic media"
        else:
            raise AssertionError("media_wait must propagate the job exception")

    asyncio.run(propagates())
    ok("media_wait still propagates a job exception on an open loop")


media_wait_shutdown()


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


async def link_stability():
    from fake_link import FakeLink
    # A lost MAX connection leaves a call alone (its ws2 and ICE decide), and
    # is told once, not at every attempt to connect again.
    told = []
    class UI:
        def connected(self, account, on):
            told.append(on)
            return False
        def signin(self, *_a):
            return False
    account = bm.Backend(UI(), FakeLink()).accounts["max"]
    account.online = True
    call = account.call = bm.VoiceCall("talk", "test-person", True, lambda *args: None)
    call.accepted, call.state = True, "active"
    with patch.object(bm, "log_line") as log:
        for _n in range(3):
            await account.on_disconnect("ConnectionError()")
    assert not call.closed and account.call is call and log.call_count == 1
    while bm.GLib.MainContext.default().iteration(False):
        pass
    assert told == [False]
    await call.end("HUNGUP")
    # Two starts at once (a double tap, a switch while the keyring answers):
    # one connection.
    fake = FakeLink()
    backend = bm.Backend(UI(), fake)
    backend.loop = asyncio.get_running_loop()
    slow = asyncio.Event()
    async def signed_in():
        await slow.wait()
        return True
    fake.signed_in = signed_in
    lives = []
    async def live(self):
        lives.append(self)
        await asyncio.Event().wait()  # connected, till stopped
    with patch.object(bm, "messenger_on", return_value=True), patch.object(bm.Account, "live", live):
        starts = [asyncio.create_task(backend.begin("max", quiet=True)) for _n in range(2)]
        await asyncio.sleep(.05)
        slow.set()
        await asyncio.gather(*starts)
        await asyncio.sleep(.1)
        assert len(lives) == 1
        task = backend.accounts["max"].task
        await backend.accounts["max"].stop()
        assert backend.accounts["max"].task is None and task.done()
        # The keyring failing at the start: said, and nothing hangs
        async def broken():
            raise bm.GLib.Error("no reply from the keyring")
        fake.signed_in = broken
        await backend.begin("max", quiet=True)
        assert backend.accounts["max"].task is None
    # PyMax tries again ever later while offline, and quickly once connected
    link = bm.PyMaxLink("unused")
    link.client = SimpleNamespace(extra_config=SimpleNamespace(reconnect_delay=bm.RECONNECT_FIRST))
    events = []
    async def on_disconnect(why):
        events.append(why)
    link.events = SimpleNamespace(on_disconnect=on_disconnect)
    delays = []
    for _n in range(6):
        await link._disconnected(OSError("no network"), True, link.client.extra_config.reconnect_delay)
        delays.append(link.client.extra_config.reconnect_delay)
    assert delays == [6.0, 12.0, 24.0, 48.0, 60.0, 60.0] and len(events) == 6
    ok("a lost connection leaves a call; one start per account; the keyring's failure; backoff")


async def voice_only():
    # As shipped (#55): no video at all — not offered, not decoded, a video
    # invitation rung and answered by voice.
    from fake_link import FakeLink
    bm.SETTINGS.set("calls_video", False)
    bm.video_supported.cache_clear()
    try:
        assert not bm.video_on() and not bm.video_calls()
        fake = FakeLink(can={"calls"})
        account = bm.Backend(object(), fake).accounts["max"]
        account.online = True
        made = []
        with patch.object(account, "new_call", side_effect=lambda *a, **k: made.append(k) or Mock()):
            await account.on_call_frame(137, {"conversationId": "v", "callerId": 20,
                                              "vcp": literal(params), "type": "VIDEO"})
        assert made == [{"video": False}]
        from gi.repository import Gst
        Gst.init(None)
        audio = bm.CallAudio.__new__(bm.CallAudio)
        audio.Gst, audio.closed, audio.failed_bins = Gst, False, []
        audio.remote_bin, audio.video_ok = None, bm.video_on()
        audio.pipeline = Gst.Pipeline.new("call")
        src = Gst.ElementFactory.make("videotestsrc", None)
        audio.pipeline.add(src)
        caps = Gst.Caps.from_string("application/x-rtp,media=video,encoding-name=VP8")
        pad = SimpleNamespace(direction=Gst.PadDirection.SRC, get_current_caps=lambda: caps,
                              link=lambda sink: Gst.PadLinkReturn.OK)
        audio._received(None, pad)
        assert audio.remote_bin is None  # the peer's video, if it comes, goes undecoded
        audio.pipeline.set_state(Gst.State.NULL)
    finally:
        bm.SETTINGS.set("calls_video", True)
        bm.video_supported.cache_clear()
    ok("voice only (#55): no video offered, decoded, or answered")


async def calls_switched_off():
    from fake_link import FakeLink
    fake = FakeLink(can={"calls"})
    account = bm.Backend(object(), fake).accounts["max"]
    account.online = True
    invitation = {"conversationId": "off", "callerId": 20, "vcp": literal(params)}
    made = []
    with patch.object(account, "new_call", side_effect=lambda *a, **k: made.append((a, k)) or Mock()):
        with patch.object(bm, "calls_allowed", lambda video: False):
            await account.on_call_frame(137, invitation)
        assert not made  # not rung here at all
        with patch.object(bm, "calls_allowed", lambda video: not video), \
                patch.object(bm, "video_calls", lambda: False):
            await account.on_call_frame(137, dict(invitation, type="VIDEO"))
        assert made and made[-1][1]["video"] is False  # rings as a voice call
    ok("voice and video calls switched off apart: not rung, or a video call as a voice one")


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
        # Processors with room: no step down; the whole system busy: one, even
        # if the encoder keeps up (640×480 kept two of four cores busy).
        await call.adapt_video(15, 15, idle=.5)
        assert call.audio.video_size == (320, 240, 15)
        call.audio.video_size = (480, 360, 15)
        await call.adapt_video(15, 15, idle=.1)  # one busy look: no step (a camera starting is busy)
        assert call.audio.video_size == (480, 360, 15)
        await call.adapt_video(15, 15, idle=.1)  # two in a row: a step down
        assert call.audio.video_size == (320, 240, 15) and call.video
        idle, total = bm.system_cpu()
        assert 0 <= idle <= total
        await call.adapt_video(3, 15)
        await call.adapt_video(3, 15)
        assert call.audio.video_size == (160,120,10) and call.video
        assert bm.VIDEO_START[0] == (320, 240, 15)  # the next call starts no smaller than 320×240
        await call.adapt_video(3, 15)
        await call.adapt_video(3, 15)
        # at its smallest the picture stays: the program never switches the camera off
        assert call.video and call.audio.camera and call.video_wanted and not call.video_error
        bm.VIDEO_START[0] = bm.VIDEO_SIZES[1]
        await switch(False)
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
        await socket.notify("media-settings-changed", participantId="remote",
                            mediaSettings={"isVideoEnabled": False, "isAudioEnabled": False})
        await until(lambda: call.remote_audio is False and call.remote_video is False)
        # as MAX really says it: a switched-off one is left out, not false
        await socket.notify("media-settings-changed", participantId="remote",
                            mediaSettings={"isAudioEnabled": True, "isVideoEnabled": True})
        await until(lambda: call.remote_audio is True and call.remote_video is True)
        await socket.notify("media-settings-changed", participantId="remote",
                            mediaSettings={"isVideoEnabled": True})
        await until(lambda: call.remote_audio is False and call.remote_video is True)
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


async def signalling_tolerance():
    # What the media do not need never ends a talk: an error frame no command
    # waits for (a late reply, a refused candidate), a candidate the service
    # refuses, a malformed one from the peer. Only a fatal error ends it.
    class Refusing(Socket):
        async def send(self, raw):
            value = json.loads(raw) if raw != "pong" else raw
            if isinstance(value, dict) and "candidate" in (value.get("data") or {}):
                self.sent.append(value)
                await self.queue.put(json.dumps({"type": "error", "sequence": value["sequence"],
                                                 "error": "participant-not-found"}))
                return
            await super().send(raw)
    socket = Refusing()
    states = []
    call = bm.VoiceCall("tolerant", "test-person", False,
                        lambda call, state: states.append(state), audio=Audio,
                        connect=lambda *args, **kwargs: socket)
    call.start(dict(params))
    await until(lambda: "change-participant-state" in socket.commands())
    await socket.notify("accepted-call", participantId="remote")
    await until(lambda: call.local_sent)
    Audio.made[-1].state("connected")
    with patch.object(bm, "log_line") as log:
        call.candidate({"candidate": "refused", "sdpMLineIndex": 0})
        await socket.queue.put(json.dumps({"type": "error", "sequence": 999, "error": "private-text"}))
        await socket.queue.put(json.dumps({"type": "error", "error": "illegal-participant-state"}))
        for bad in (None, {"sdpMLineIndex": 0}, "text"):
            await socket.notify("transmitted-data", participantId="remote", data={"candidate": bad})
        await asyncio.sleep(.1)
        assert not call.closed and states[-1] == "active", states
        logged = [c.args[0] for c in log.call_args_list]
        assert "voice call: candidate not acknowledged" in logged
        assert "voice call: service error other" in logged  # the untrusted text is not logged
        assert "voice call: service error illegal-participant-state" in logged
        assert logged.count("voice call: invalid candidate skipped") == 3
        assert not any("private" in line for line in logged)
    await socket.queue.put(json.dumps({"type": "error", "error": "conversation-ended"}))
    await until(lambda: call.closed)
    await asyncio.gather(call.task, return_exceptions=True)
    assert states[-1] == "failed" and Audio.made[-1].closed

    # The end is told at once, before the hang-up is through (a slow network),
    # and a local hang-up closing the socket under recv() is no failure.
    gate = asyncio.Event()
    class Slow(Socket):
        async def send(self, raw):
            if raw != "pong" and json.loads(raw).get("command") == "hangup":
                await gate.wait()
            await super().send(raw)
        async def recv(self):
            if self.closed:
                raise ConnectionError("closed")
            closing = asyncio.create_task(self.closing.wait())
            got = asyncio.create_task(self.queue.get())
            await asyncio.wait({closing, got}, return_when=asyncio.FIRST_COMPLETED)
            closing.cancel()
            if got.done():
                return got.result()
            got.cancel()
            raise ConnectionError("closed")
        async def close(self):
            self.closed = True
            self.closing.set()
    socket = Slow()
    socket.closing = asyncio.Event()
    states = []
    call = bm.VoiceCall("slow-hangup", "test-person", False,
                        lambda call, state: states.append(state), audio=Audio,
                        connect=lambda *args, **kwargs: socket)
    with patch.object(bm, "log_line") as log:
        call.start(dict(params))
        await until(lambda: "change-participant-state" in socket.commands())
        ending = asyncio.create_task(call.end("CANCELED"))
        await until(lambda: states and states[-1] == "ended")
        assert not ending.done() and "hangup" not in socket.commands()  # told first
        gate.set()
        await ending
        await asyncio.gather(call.task, return_exceptions=True)
        assert socket.commands()[-1] == "hangup" and socket.closed
        assert states.count("ended") == 1
        assert not any("signalling failed" in c.args[0] for c in log.call_args_list)
    ok("refused candidates, stray and malformed frames keep a call; the end is told before the hang-up goes")


async def media_state_transitions():
    # Remaining MSG2-12 (#84): PLAYING, rebuild_sender's old NULL and remote()'s
    # video-bin NULL still ran on the loop. Delayed fakes keep the loop moving
    # and preserve caller order; close/stale generation/failure drop the work.

    async def poke_while(pending):
        ticks = []
        while not pending.done():
            ticks.append(True)
            await asyncio.sleep(.01)
        return ticks

    def collecting_pipeline():
        pipe = SimpleNamespace(added=[], removed=[], state=None)
        pipe.add = pipe.added.append
        def remove(el):
            assert el not in pipe.removed, "video bin removed twice"
            pipe.removed.append(el)
        pipe.remove = remove
        pipe.set_state = lambda state: setattr(pipe, "state", state) or "success"
        return pipe

    # start PLAYING in flight: the loop stays responsive, then PLAYING, then NULL.
    release = threading.Event()
    order = []
    pipeline = DelayedState(release, order, "pipe")
    audio = stand_in_audio(pipeline)
    starting = asyncio.create_task(audio.start())
    try:
        await until(pipeline.started.is_set)
        began = time.monotonic()
        audio.close()
        assert time.monotonic() - began < .5 and not starting.done()
        poker = asyncio.create_task(poke_while(starting))
        await asyncio.sleep(.05)
        assert not starting.done()
        release.set()
        await starting
        ticks = await poker
        assert ticks, "PLAYING blocked the loop"
        assert audio.stopped.result(5) == "success"
        assert order == [("pipe", "playing"), ("pipe", "null")]
    finally:
        release.set()
        if not starting.done():
            starting.cancel()
    ok("start PLAYING leaves the loop free; close in flight keeps PLAYING then NULL")

    # PLAYING still queued behind a stuck FIFO job: close queues NULL after it.
    occupied, hold = threading.Event(), threading.Event()
    release = threading.Event()
    release.set()
    order = []
    pipeline = DelayedState(release, order, "pipe")
    audio = stand_in_audio(pipeline)
    bm.MEDIA_WORKER.submit(lambda: occupied.set() or hold.wait(5))
    assert occupied.wait(5)
    try:
        starting = asyncio.create_task(audio.start())
        await asyncio.sleep(.05)
        assert not pipeline.started.is_set() and not starting.done()
        audio.close()
        hold.set()
        await starting
        assert audio.stopped.result(5) == "success"
        assert order == [("pipe", "playing"), ("pipe", "null")]
    finally:
        hold.set()
    ok("start PLAYING queued on the FIFO still runs before the close NULL")

    # PLAYING failure closes the pipeline.
    release = threading.Event()
    release.set()
    pipeline = DelayedState(release, name="fail")
    pipeline.fail = True
    audio = stand_in_audio(pipeline)
    try:
        await audio.start()
        raise AssertionError("failed PLAYING must raise")
    except RuntimeError:
        pass
    assert audio.closed and audio.pipeline is None
    ok("start PLAYING failure closes the pipeline")

    # rebuild_sender: old NULL in flight, loop free, then a new sender; close
    # and a stale generation do not install one; FAILURE keeps the old bin.
    release = threading.Event()
    delayed = DelayedState(release, name="old")
    old = FakeBin(delayed, pt=102)
    pipe = collecting_pipeline()
    audio = stand_in_audio(pipe)
    audio.video_bin, audio.video_pad = old, "pad"
    made = []
    audio._sender_bin = lambda payload: made.append(FakeBin(pt=payload)) or made[-1]
    rebuilding = asyncio.create_task(audio.rebuild_sender())
    try:
        await until(delayed.started.is_set)
        poker = asyncio.create_task(poke_while(rebuilding))
        await asyncio.sleep(.05)
        assert not rebuilding.done()
        release.set()
        assert await rebuilding is True
        assert await poker
        assert pipe.removed == [old] and made and audio.video_bin is made[0]
        assert made[0].pt == 102 and made[0].synced and made[0].encoder_rate == bm.VIDEO_BITRATE[320]
    finally:
        release.set()
        if not rebuilding.done():
            rebuilding.cancel()
    ok("rebuild_sender waits for old NULL off the loop and keeps the payload")

    release = threading.Event()
    delayed = DelayedState(release, name="stale")
    old = FakeBin(delayed)
    audio = stand_in_audio(collecting_pipeline())
    audio.video_bin, audio.video_pad = old, "pad"
    audio._sender_bin = lambda _payload: FakeBin()
    generation = audio.media_generation
    rebuilding = asyncio.create_task(audio.rebuild_sender())
    try:
        await until(delayed.started.is_set)
        audio.close()
        release.set()
        assert await rebuilding is False
        assert audio.media_generation != generation and audio.video_bin is None
    finally:
        release.set()
        if not rebuilding.done():
            rebuilding.cancel()
    ok("rebuild_sender drops a stale generation when close runs in flight")

    release = threading.Event()
    release.set()
    delayed = DelayedState(release, name="fail")
    delayed.fail = True
    old = FakeBin(delayed)
    pipe = collecting_pipeline()
    audio = stand_in_audio(pipe)
    audio.video_bin, audio.video_pad = old, "pad"
    audio._sender_bin = lambda _payload: FakeBin()
    assert await audio.rebuild_sender() is False
    assert audio.video_bin is old and not pipe.removed
    ok("rebuild_sender FAILURE keeps the old sender")

    # remote(): video-bin NULL off the loop; payload after it; close skips it.
    offer = {"type": "offer", "sdp": "v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 102\r\na=rtpmap:102 VP8/90000\r\n"}
    promised = []

    def stub_remote(audio, h264=False):
        audio.RTC = SimpleNamespace(WebRTCSDPType=SimpleNamespace(OFFER="offer", ANSWER="answer"),
                                    WebRTCSessionDescription=SimpleNamespace(new=lambda kind, sdp: (kind, sdp)),
                                    WebRTCRTPTransceiverDirection=SimpleNamespace(RECVONLY="recvonly"))
        audio.Sdp = SimpleNamespace(SDPResult=SimpleNamespace(OK="ok"),
                                    SDPMessage=SimpleNamespace(new_from_text=lambda _sdp: ("ok", object())))
        async def promise(command, *_args):
            promised.append(command)
        audio._promise = promise
        if h264:
            audio.Gst.ElementFactory = SimpleNamespace(
                find=lambda n: object() if n in ("avdec_h264", "openh264dec") else None)

    class FakePad:
        def __init__(self):
            self.direction = self.codecs = None
            self.transceiver = SimpleNamespace(set_property=self._set)

        def _set(self, key, value):
            if key == "direction":
                self.direction = value
            else:
                self.codecs = value

        def get_property(self, name):
            assert name == "transceiver"
            return self.transceiver

    release = threading.Event()
    delayed = DelayedState(release, name="video")
    video = FakeBin(delayed, pt=96)
    audio = stand_in_audio(StoppingPipeline())
    audio.video_bin = video
    stub_remote(audio)
    remoting = asyncio.create_task(audio.remote(offer))
    try:
        await until(delayed.started.is_set)
        poker = asyncio.create_task(poke_while(remoting))
        await asyncio.sleep(.05)
        assert not remoting.done() and video.pt == 96
        release.set()
        await remoting
        assert await poker
        assert video.pt == 102 and video.synced and promised == ["set-remote-description"]
    finally:
        release.set()
        if not remoting.done():
            remoting.cancel()
    ok("remote() waits for video-bin NULL off the loop, then the payload and SDP")

    promised.clear()
    release = threading.Event()
    delayed = DelayedState(release, name="closed")
    video = FakeBin(delayed, pt=96)
    audio = stand_in_audio(StoppingPipeline())
    audio.video_bin = video
    stub_remote(audio)
    remoting = asyncio.create_task(audio.remote(offer))
    try:
        await until(delayed.started.is_set)
        audio.close()
        release.set()
        await remoting
        assert video.pt == 96 and not video.synced and promised == []
    finally:
        release.set()
        if not remoting.done():
            remoting.cancel()
    ok("remote() close in flight skips the payload change and set-remote-description")

    # remote() VP8 NULL FAILURE must not mutate a still-running bin or apply SDP 102.
    promised.clear()
    release = threading.Event()
    release.set()
    delayed = DelayedState(release, name="vp8-fail")
    delayed.fail = True
    video = FakeBin(delayed, pt=96)
    audio = stand_in_audio(StoppingPipeline())
    audio.video_bin = video
    stub_remote(audio)
    with patch.object(bm, "log_line") as log:
        try:
            await audio.remote(offer)
            raise AssertionError("VP8 NULL FAILURE must fail negotiation")
        except RuntimeError as exc:
            assert "video bin failed to stop" in str(exc)
    assert video.pt == 96 and not video.synced and promised == []
    assert audio.video_bin is video
    assert any("video bin failed to stop" in c.args[0] for c in log.call_args_list)
    ok("remote() VP8 NULL FAILURE leaves payload and does not apply SDP")

    # remote() H264: NULL first; FAILURE keeps the running bin and skips SDP.
    h264_offer = {"type": "offer", "sdp":
                  "v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 102\r\na=rtpmap:102 H264/90000\r\n"}
    promised.clear()
    release = threading.Event()
    release.set()
    delayed = DelayedState(release, name="h264-fail")
    delayed.fail = True
    video = FakeBin(delayed, pt=96)
    pipe = collecting_pipeline()
    audio = stand_in_audio(pipe)
    pad, released = FakePad(), []
    audio.video_bin, audio.video_pad = video, pad
    audio.rtc = SimpleNamespace(release_request_pad=released.append)
    stub_remote(audio, h264=True)
    with patch.object(bm, "log_line") as log:
        try:
            await audio.remote(h264_offer)
            raise AssertionError("H264 NULL FAILURE must fail negotiation")
        except RuntimeError as exc:
            assert "video bin failed to stop" in str(exc)
    assert audio.video_bin is video and audio.video_pad is pad
    assert not pipe.removed and released == [] and promised == []
    assert pad.direction is None
    assert any("video bin failed to stop" in c.args[0] for c in log.call_args_list)
    ok("remote() H264 NULL FAILURE does not remove the still-running bin")

    promised.clear()
    release = threading.Event()
    release.set()
    delayed = DelayedState(release, name="h264-ok")
    video = FakeBin(delayed, pt=96)
    pipe = collecting_pipeline()
    audio = stand_in_audio(pipe)
    pad, released = FakePad(), []
    audio.video_bin, audio.video_pad = video, pad
    audio.rtc = SimpleNamespace(release_request_pad=released.append)
    stub_remote(audio, h264=True)
    await audio.remote(h264_offer)
    assert audio.video_bin is None and pipe.removed == [video] and released == [pad]
    assert pad.direction == "recvonly" and promised == ["set-remote-description"]
    ok("remote() H264 NULL success releases the VP8 sender")

    # Overlap: remote VP8 payload 102 while rebuild_sender's NULL is in flight.
    # FIFO orders worker jobs; the lock serializes loop-side snapshot/commit.
    promised.clear()
    release = threading.Event()
    delayed = DelayedState(release, name="overlap")
    old = FakeBin(delayed, pt=96)
    pipe = collecting_pipeline()
    audio = stand_in_audio(pipe)
    audio.video_bin, audio.video_pad = old, "pad"
    made = []
    audio._sender_bin = lambda payload: made.append(FakeBin(pt=payload)) or made[-1]
    stub_remote(audio)
    rebuilding = asyncio.create_task(audio.rebuild_sender())
    remoting = None
    try:
        await until(delayed.started.is_set)
        remoting = asyncio.create_task(audio.remote(offer))
        await asyncio.sleep(.05)
        assert not remoting.done() and old.pt == 96
        release.set()
        assert await rebuilding is True
        await remoting
        assert audio.video_bin is made[0] and audio.video_bin.pt == 102
        assert old.pt == 96 and pipe.removed == [old]
        assert promised == ["set-remote-description"]
    finally:
        release.set()
        if not rebuilding.done():
            rebuilding.cancel()
        if remoting is not None and not remoting.done():
            remoting.cancel()
    ok("rebuild_sender overlapping remote() VP8 keeps the negotiated payload")

    # The other order: remote() applies 102, then rebuild installs 102, not 96.
    promised.clear()
    release = threading.Event()
    delayed = DelayedState(release, name="overlap-remote")
    old = FakeBin(delayed, pt=96)
    pipe = collecting_pipeline()
    audio = stand_in_audio(pipe)
    audio.video_bin, audio.video_pad = old, "pad"
    made = []
    audio._sender_bin = lambda payload: made.append(FakeBin(pt=payload)) or made[-1]
    stub_remote(audio)
    remoting = asyncio.create_task(audio.remote(offer))
    rebuilding = None
    try:
        await until(delayed.started.is_set)
        rebuilding = asyncio.create_task(audio.rebuild_sender())
        await asyncio.sleep(.05)
        assert not rebuilding.done()
        release.set()
        await remoting
        assert old.pt == 102
        assert await rebuilding is True
        assert audio.video_bin is made[0] and audio.video_bin.pt == 102
        assert pipe.removed == [old]
    finally:
        release.set()
        if not remoting.done():
            remoting.cancel()
        if rebuilding is not None and not rebuilding.done():
            rebuilding.cancel()
    ok("remote() overlapping rebuild_sender still rebuilds with payload 102")

    # H264 remote overlapping rebuild: the lock runs rebuild first, then
    # remote() on the new sender. Rebuild succeeds; remote() then removes
    # that sender and releases the original pad. No double-remove.
    promised.clear()
    release = threading.Event()
    delayed = DelayedState(release, name="h264-overlap")
    old = FakeBin(delayed, pt=96)
    pipe = collecting_pipeline()
    audio = stand_in_audio(pipe)
    pad, released = FakePad(), []
    audio.video_bin, audio.video_pad = old, pad
    audio.rtc = SimpleNamespace(release_request_pad=released.append)
    made = []
    audio._sender_bin = lambda payload: made.append(FakeBin(pt=payload)) or made[-1]
    stub_remote(audio, h264=True)
    rebuilding = asyncio.create_task(audio.rebuild_sender())
    remoting = None
    try:
        await until(delayed.started.is_set)
        remoting = asyncio.create_task(audio.remote(h264_offer))
        await asyncio.sleep(.05)
        assert not remoting.done()
        release.set()
        rebuilt = await rebuilding
        await remoting
        assert rebuilt is True
        assert pipe.removed == [old, made[0]]
        assert released == [pad]
        assert audio.video_bin is None and audio.video_pad is None
        assert promised == ["set-remote-description"]
    finally:
        release.set()
        if not rebuilding.done():
            rebuilding.cancel()
        if remoting is not None and not remoting.done():
            remoting.cancel()
    ok("rebuild_sender overlapping remote() H264 does not double-remove")

    # negotiate owns SDP: description waits until start() finishes; hang-up
    # during start does not create an offer.
    order = []
    gate = asyncio.Event()

    class OrderAudio(Audio):
        async def start(self):
            order.append("start")
            await gate.wait()
            order.append("started")
        async def description(self, kind):
            order.append("description")
            return {"type": kind, "sdp": "synthetic"}
        async def remote(self, value):
            order.append("remote")
            await super().remote(value)

    call = bm.VoiceCall("order", "test-person", False, lambda *_a: None, audio=OrderAudio)
    call.transmit = AsyncMock()
    call.command = AsyncMock()
    negotiating = asyncio.create_task(call.negotiate())
    await until(lambda: order == ["start"])
    poker = asyncio.create_task(poke_while(negotiating))
    await asyncio.sleep(.05)
    assert "description" not in order and not negotiating.done()
    gate.set()
    await negotiating
    assert await poker
    assert order == ["start", "started", "description"]
    ok("negotiate awaits start PLAYING before creating SDP")

    order.clear()
    gate = asyncio.Event()
    call = bm.VoiceCall("order-close", "test-person", False, lambda *_a: None, audio=OrderAudio)
    call.transmit = AsyncMock()
    call.command = AsyncMock()
    negotiating = asyncio.create_task(call.negotiate())
    await until(lambda: order == ["start"])
    assert call.audio is not None  # assigned before start(); SDP is not sent yet
    await call.end("HUNGUP")
    gate.set()
    await asyncio.wait_for(negotiating, 1)
    assert order == ["start", "started"] and "description" not in order
    assert call.audio is not None and call.audio.closed
    assert not call.transmit.called
    ok("negotiate close during start does not create SDP")

    # remote() raising (NULL FAILURE) ends the call; no answer is sent.
    class FailRemote(Audio):
        async def start(self):
            pass
        async def remote(self, value):
            raise RuntimeError("video bin failed to stop")
        async def description(self, kind):
            raise AssertionError("SDP must not be created after a failed remote")

    states = []
    call = bm.VoiceCall("fail-sdp", "test-person", True,
                        lambda _c, s: states.append(s), audio=FailRemote)
    call.offer = offer
    call.offer_ready.set()
    call.transmit = AsyncMock()
    call.command = AsyncMock()
    call.job(call.negotiate())
    await until(lambda: call.closed)
    assert call.state == "failed" and "failed" in states
    assert not call.transmit.called
    ok("negotiate remote() failure ends the call without sending SDP")


async def media_stop_observed():
    from fake_link import FakeLink
    backend = bm.Backend(object(), FakeLink())
    account = backend.accounts["max"]

    class FailedAudio:
        closed = False
        stopped = concurrent.futures.Future()
        def close(self):
            self.closed = True
    failed = FailedAudio()
    failed.stopped.set_exception(RuntimeError("synthetic stop"))
    call = account.call = bm.VoiceCall("stop-fail", 10, False, lambda *_a: None)
    call.accepted, call.audio, call.socket = True, failed, Socket()
    lines = []
    with patch.object(bm, "log_line", side_effect=lines.append):
        await backend.hangup_calls()
    assert any("media stop failed" in line for line in lines)
    ok("hangup_calls logs a failed media stop future")

    class StuckAudio:
        closed = False
        stopped = concurrent.futures.Future()
        def close(self):
            self.closed = True
    stuck = StuckAudio()
    account.call = call = bm.VoiceCall("stop-wait", 10, False, lambda *_a: None)
    call.accepted, call.audio, call.socket = True, stuck, Socket()
    began = time.monotonic()
    with patch.object(bm, "MEDIA_STOP_WAIT", .05), patch.object(bm, "log_line") as log:
        await backend.hangup_calls()
    assert time.monotonic() - began < .5
    assert any("media stop still running" in c.args[0] for c in log.call_args_list)
    assert not stuck.stopped.cancelled()
    ok("hangup_calls logs a media stop still running after the bound")

    class TrackingPipeline:
        def __init__(self):
            self.states, self.children = [], []
        def add(self, element):
            self.children.append(element)
        def set_state(self, state):
            self.states.append(state)
            return "success"

    def occupy_media():
        occupied, hold = threading.Event(), threading.Event()
        bm.MEDIA_WORKER.submit(lambda: occupied.set() or hold.wait(5))
        assert occupied.wait(5)
        return hold

    def media_barrier():
        return bm.MEDIA_WORKER.submit(lambda: None).result(5)

    # Queue pipeline NULL behind a blocked MEDIA_WORKER job; hangup_calls
    # times out; loop turns must not cancel the source; NULL still runs.
    hold = occupy_media()
    pipeline = TrackingPipeline()
    audio = stand_in_audio(pipeline)
    account.call = call = bm.VoiceCall("stop-fifo", 10, False, lambda *_a: None)
    call.accepted, call.audio, call.socket = True, audio, Socket()
    audio.close()
    source = audio.stopped
    assert source is not None and not source.done() and pipeline.states == []
    try:
        with patch.object(bm, "MEDIA_STOP_WAIT", .05), patch.object(bm, "log_line") as log:
            await backend.hangup_calls()
        assert any("media stop still running" in c.args[0] for c in log.call_args_list)
        assert not source.cancelled() and not source.done()
        for _ in range(10):
            await asyncio.sleep(0)
        assert not source.cancelled() and pipeline.states == []
        hold.set()
        media_barrier()
        assert not source.cancelled() and source.result(5) == "success"
        assert pipeline.states == ["null"], "queued pipeline NULL was skipped"
    finally:
        hold.set()
    ok("hangup_calls timeout leaves a queued pipeline NULL running")

    # Outer shutdown cancels hangup_calls itself (do_shutdown's future.cancel()).
    hold = occupy_media()
    pipeline = TrackingPipeline()
    audio = stand_in_audio(pipeline)
    account.call = call = bm.VoiceCall("stop-cancel", 10, False, lambda *_a: None)
    call.accepted, call.audio, call.socket = True, audio, Socket()
    audio.close()
    source = audio.stopped
    hanging = None
    try:
        with patch.object(bm, "MEDIA_STOP_WAIT", 5), patch.object(bm, "log_line") as log:
            hanging = asyncio.create_task(backend.hangup_calls())
            await until(lambda: call.hangup_done.is_set() and not hanging.done())
            await asyncio.sleep(.05)  # inside asyncio.wait on the media stop
            assert not hanging.done()
            hanging.cancel()
            try:
                await hanging
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("hangup_calls should be cancelled")
        assert any("media stop still running" in c.args[0] for c in log.call_args_list)
        assert not source.cancelled() and not source.done()
        for _ in range(10):
            await asyncio.sleep(0)
        assert not source.cancelled() and pipeline.states == []
        hold.set()
        media_barrier()
        assert not source.cancelled() and source.result(5) == "success"
        assert pipeline.states == ["null"], "queued pipeline NULL was skipped"
    finally:
        hold.set()
        if hanging is not None and not hanging.done():
            hanging.cancel()
    ok("hangup_calls task cancellation leaves a queued pipeline NULL running")


async def main():
    await media_state_transitions()
    await media_stop_observed()
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
    await link_stability()
    await voice_only()
    await calls_switched_off()
    await busy_invitation()
    await quit_hangup()
    await quit_during_dial()
    await quit_during_dial(fails=True)
    await missed_calls()
    await signalling_tolerance()


asyncio.run(main())
