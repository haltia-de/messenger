# SPDX-License-Identifier: GPL-3.0-or-later
"""Real WebRTC peers on synthetic audio; no account or microphone needed.
Run inside the Messenger Flatpak when the host has no GstWebRTC/libnice.
"""
import asyncio
from common import load, ok

bm = load()
bm.SETTINGS.set("calls_video", True)  # «Видеозвонки» on here (off by default, #55); voice-only below


def phone_streams():
    Gst, _rtc, _sdp = bm.call_media()
    Gst.init(None)
    # Real PulseAudio elements, left in NULL: no microphone or speaker is
    # opened. Check both the send pipeline and the dynamically added sink.
    audio = bm.CallAudio.__new__(bm.CallAudio)
    audio.Gst = Gst
    for description in ("pulsesrc name=phone ! fakesink",
                        "audiotestsrc ! pulsesink name=phone"):
        pipeline = Gst.parse_launch(description)
        try:
            audio._phone_streams(pipeline)
            properties = pipeline.get_by_name("phone").get_property("stream-properties")
            assert isinstance(properties, Gst.Structure)
            assert properties.get_name() == "props"
            assert properties.get_string("media.role") == "phone"
            assert properties.n_fields() == 1
            assert not properties.has_field("filter.want")
        finally:
            pipeline.set_state(Gst.State.NULL)
    ok("call capture and playback set only the phone role as Gst.Structure without opening audio")


async def ringtone():
    from gi.repository import GLib
    bm.save_setting("ring_volume", ".4")
    ring = bm.CallRinger(sink="fakesink name=heard sync=false signal-handoffs=true")
    try:
        ring.start()
        pipeline = ring.pipeline
        assert pipeline is not None
        received = [0]
        def handoff(_sink, buffer, _pad):
            received[0] += buffer.get_size()
        pipeline.get_by_name("heard").connect("handoff", handoff)
        assert abs(pipeline.get_by_name("level").get_property("volume") - .4) < .00001
        ring.start()  # An updated caller name cannot start another melody.
        assert ring.pipeline is pipeline
        deadline = asyncio.get_running_loop().time() + 1.0
        while asyncio.get_running_loop().time() < deadline:
            while GLib.MainContext.default().iteration(False):
                pass
            await asyncio.sleep(.01)
        # The sink has no clock: more than one complete phrase proves EOS
        # restarts playback, including its baked-in pause, rather than stopping.
        assert received[0] > 2 * 24000 * 4 * 2
        assert ring.pipeline is pipeline
        assert pipeline.get_state(0)[1] == bm.call_media()[0].State.PLAYING
    finally:
        ring.stop()
        ring.stop()
    assert ring.pipeline is None and ring.timer is None
    assert pipeline.get_state(0)[1] == bm.call_media()[0].State.NULL
    # A broken output leaves neither a timer nor a partially built pipeline.
    ring = bm.CallRinger(sink="no_such_audio_element")
    ring.start()
    assert ring.pipeline is None and ring.timer is None
    # An unavailable WAV also releases its pipeline and poll source.
    ring = bm.CallRinger(sink="fakesink", path="/no/such/ringtone.wav")
    ring.start()
    deadline = asyncio.get_running_loop().time() + 1
    while ring.pipeline is not None and asyncio.get_running_loop().time() < deadline:
        while GLib.MainContext.default().iteration(False):
            pass
        await asyncio.sleep(.01)
    assert ring.pipeline is None and ring.timer is None
    ok("ringtone WAV, volume, repeat, repeated start, stop, missing file and unavailable output without audio devices")


async def pair(passive=False):
    loop = asyncio.get_running_loop()
    states = [set(), set()]
    peers = []
    samples = [0, 0]
    early_candidates, callback_errors = [], []
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: callback_errors.append(context))
    def candidate(n, value):
        if len(peers) < 2:
            early_candidates.append((n, value))
        else:
            peers[1 - n].add_candidate(value)
    try:
        offer = None
        for n in range(2):
            peers.append(bm.CallAudio(loop, lambda value, n=n: candidate(n, value),
                                     states[n].add, {},
                                     source="audiotestsrc is-live=true wave=sine",
                                     sink="fakesink name=received sync=false signal-handoffs=true"))
            if n == 0:
                offer = await peers[0].description("offer")
        assert "m=audio" in offer["sdp"] and "m=video" in offer["sdp"]
        assert "opus/48000/2" in offer["sdp"].lower() and " red/" not in offer["sdp"]
        if passive:
            offer["sdp"] = offer["sdp"].replace("a=setup:actpass", "a=setup:passive")
            # Android also offers RED before Opus and an active video m-line.
            offer["sdp"] = offer["sdp"].replace("RTP/SAVPF 111", "RTP/SAVPF 63 111")
            offer["sdp"] = offer["sdp"].replace("a=rtpmap:111", "a=rtpmap:63 red/48000/2\r\na=fmtp:63 111/111\r\na=rtpmap:111")
            offer["sdp"] = offer["sdp"].replace("a=inactive", "a=sendrecv")
        for n, value in early_candidates:
            candidate(n, value)
        early_candidates.clear()
        await peers[1].remote(offer)
        answer = await peers[1].description("answer")
        if passive:
            assert "a=setup:active" in answer["sdp"]
        await peers[0].remote(answer)
        connected = loop.time() + 15
        while loop.time() < connected and not all("connected" in s for s in states):
            await asyncio.sleep(.05)
        assert all("connected" in s for s in states), states
        for n, peer in enumerate(peers):
            # The receive bin is created only after the first RTP packet.
            deadline = loop.time() + 5
            sink = None
            while loop.time() < deadline:
                sink = peer.pipeline.get_by_name("received")
                if sink is not None:
                    break
                await asyncio.sleep(.05)
            assert sink is not None
            def handoff(*args, n=n):
                samples[n] += 1
            sink.connect("handoff", handoff)
        await asyncio.sleep(.5)
        assert all(n > 5 for n in samples), samples
        for peer in peers:
            counters = await peer.stats()
            assert any(c.get("packets-received", 0) > 0 for c in counters), counters
            assert all(set(c) <= {"type", "packets-received", "packets-sent", "packets-lost",
                                  "jitter", "round-trip-time", "bytes-received", "bytes-sent",
                                  "nack-count"} for c in counters)
        assert not callback_errors, callback_errors
        ok("passive offer, active answer and two-way Opus" if passive else "outgoing offer with reserved video and two-way Opus")
    finally:
        pipelines = [peer.pipeline for peer in peers]
        handlers = [(peer.rtc, list(peer.signals)) for peer in peers]
        for peer in peers:
            peer.close()
            peer.close()  # cleanup is idempotent, including partially built pipelines
            assert peer.pipeline is None and peer.rtc is None and peer.bus is None
        assert all(pipeline.get_state(0)[1] == peers[0].Gst.State.NULL for pipeline in pipelines)
        assert all(not rtc.handler_is_connected(handler) for rtc, ids in handlers for handler in ids)
        loop.set_exception_handler(previous_handler)


async def main():
    assert bm.calls_supported()  # the complete Flatpak media stack is advertised
    phone_streams()
    await ringtone()
    broken = bm.CallAudio.__new__(bm.CallAudio)
    try:
        broken.__init__(asyncio.get_running_loop(), lambda c: None, lambda s: None,
                        {"turn": {"urls": ["invalid:server"]}},
                        source="audiotestsrc is-live=true", sink="fakesink")
    except ValueError:
        assert broken.closed and broken.pipeline is None and broken.rtc is None and broken.bus is None
    else:
        raise AssertionError("invalid TURN scheme accepted")
    await pair()
    await pair(passive=True)


asyncio.run(main())
