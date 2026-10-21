# SPDX-License-Identifier: GPL-3.0-or-later
"""Real WebRTC peers on synthetic audio; no account or microphone needed.
Run inside the Messenger Flatpak when the host has no GstWebRTC/libnice.
"""
import asyncio
from common import load, ok

bm = load()


async def video_pair():
    import os
    os.environ["HALTIA_CAMERA_SOURCE"] = "videotestsrc"
    loop = asyncio.get_running_loop()
    peers, early = [], []
    states = [set(), set()]
    frames = [{False: 0, True: 0}, {False: 0, True: 0}]
    errors = []
    loop.set_exception_handler(lambda _l, c: errors.append(c))
    def candidate(n, value):
        if len(peers) < 2:
            early.append((n, value))
        else:
            peers[1-n].add_candidate(value)
    async def wait(predicate):
        deadline = loop.time() + 15
        while not predicate() and loop.time() < deadline:
            await asyncio.sleep(.05)
        assert predicate(), (states, frames, errors)
    try:
        for n in range(2):
            peer = bm.CallAudio(loop, lambda v, n=n: candidate(n,v), states[n].add, {},
                                source="audiotestsrc is-live=true", sink="fakesink sync=false", video_payload=100 if n == 0 else 96)
            peers.append(peer)
            def frame(own, picture, n=n):
                w,h,data = picture
                assert w > 0 and h > 0 and len(data) == w*h*4
                frames[n][own] += 1
            peer.frame = frame
            assert peer.camera is None
        offer = await peers[0].description("offer")
        assert "a=rtpmap:100 VP8/90000" in offer["sdp"]
        assert "VP8/90000" in offer["sdp"] and "a=sendrecv" in offer["sdp"].split("m=video")[1]
        for n,v in early:
            candidate(n,v)
        await peers[1].remote(offer)
        await peers[0].remote(await peers[1].description("answer"))
        await wait(lambda: all("connected" in s for s in states))
        # Upgrade the established voice call without renegotiation or opening
        # a camera before a tap. Both peers exchange decoded synthetic frames.
        for peer in peers:
            assert peer.set_video(True)
        await wait(lambda: all(f[False] > 10 and f[True] > 10 for f in frames))
        cameras = [p.camera for p in peers]
        for peer in peers:
            assert peer.set_video(False) is False
            assert peer.camera is None
        assert all(c.get_state(0)[1] == peers[0].Gst.State.NULL for c in cameras)
        await asyncio.sleep(.3)
        count = [f[True] for f in frames]
        await asyncio.sleep(.4)
        assert count == [f[True] for f in frames]
        # Re-enable after releasing the device; frame timestamps must remain valid.
        for peer in peers:
            peer.set_video(True)
        await wait(lambda: all(f[True] > count[n] + 5 for n,f in enumerate(frames)))
        assert not errors, errors
        assert not any("failed" in s for s in states), states
        ok("two-way VP8, visible own previews, voice-to-video upgrade, immediate camera release and restart")
    finally:
        for peer in peers:
            peer.close()
            peer.close()


asyncio.run(video_pair())


async def h264_receive():
    """An independent H264-only phone peer, with two-way Opus preserved."""
    Gst, RTC, Sdp = bm.call_media()
    if not Gst.ElementFactory.find("x264enc") or not Gst.ElementFactory.find("avdec_h264"):
        print("H264 fixture unavailable; VP8 test remains mandatory")
        return
    loop = asyncio.get_running_loop()
    peers, early = [], []
    frames, states = [], [set(), set()]
    def candidate(n, value):
        if len(peers) == 2:
            peers[1-n].add_candidate(value)
        else:
            early.append((n, value))
    phone = bm.CallAudio.__new__(bm.CallAudio)
    phone.Gst, phone.RTC, phone.Sdp = Gst, RTC, Sdp
    phone.loop, phone.candidate, phone.status = loop, lambda v: candidate(0, v), states[0].add
    phone.closed, phone.remote_set, phone.pending = False, False, []
    phone.camera = phone.video_bin = phone.video_pad = phone.frame = None
    phone.video_generation = 0
    phone.sink = "fakesink sync=false"
    phone.pipeline = Gst.parse_launch(
        "webrtcbin name=rtc bundle-policy=max-bundle "
        "audiotestsrc is-live=true ! audioconvert ! audioresample "
        "! audio/x-raw,rate=48000,channels=1 ! opusenc ! rtpopuspay pt=111 "
        "! application/x-rtp,media=audio,encoding-name=OPUS,payload=111,clock-rate=48000,encoding-params=(string)2 ! rtc. "
        "videotestsrc is-live=true ! video/x-raw,width=320,height=240,framerate=15/1 "
        "! videoconvert ! x264enc tune=zerolatency speed-preset=ultrafast key-int-max=15 "
        "! video/x-h264,profile=constrained-baseline ! rtph264pay pt=102 config-interval=-1 "
        "! application/x-rtp,media=video,encoding-name=H264,payload=102,clock-rate=90000 ! rtc.")
    phone.rtc = phone.pipeline.get_by_name("rtc")
    phone.signals = [phone.rtc.connect(name, method) for name, method in (
        ("on-ice-candidate", phone._candidate), ("pad-added", phone._received),
        ("notify::connection-state", phone._state))]
    phone.bus = phone.pipeline.get_bus()
    phone.bus.set_sync_handler(phone._bus, None)
    phone.pipeline.set_state(Gst.State.PLAYING)
    peers.append(phone)
    try:
        receiver = bm.CallAudio(loop, lambda v: candidate(1,v), states[1].add, {},
                                source="audiotestsrc is-live=true", sink="fakesink sync=false")
        peers.append(receiver)
        receiver.frame = lambda own, frame: frames.append(frame) if not own else None
        offer = await phone.description("offer")
        await receiver.remote(offer)
        answer = await receiver.description("answer")
        assert "H264/90000" in answer["sdp"]
        assert "a=recvonly" in answer["sdp"].split("m=video")[1]
        await phone.remote(answer)
        for n, value in early:
            candidate(n, value)
        deadline = loop.time() + 15
        while len(frames) < 5 and loop.time() < deadline:
            await asyncio.sleep(.05)
        assert len(frames) >= 5, states
        assert receiver.camera is None and receiver.video_bin is None
        assert not any("failed" in s for s in states), states
        ok("H264-only incoming video decoded; camera stays closed; Opus connection survives")
    finally:
        for peer in peers:
            peer.close()


asyncio.run(h264_receive())
