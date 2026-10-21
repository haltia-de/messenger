# SPDX-License-Identifier: GPL-3.0-or-later
"""Real WebRTC peers on synthetic audio; no account or microphone needed.
Run inside the Messenger Flatpak when the host has no GstWebRTC/libnice.
"""
import asyncio
from common import load, ok

bm = load()


async def pair(passive=False):
    loop = asyncio.get_running_loop()
    states = [set(), set()]
    peers = []
    samples = [0, 0]
    def candidate(n, value):
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
        ok("passive offer, active answer and two-way Opus" if passive else "outgoing offer with inactive video and two-way Opus")
    finally:
        for peer in peers:
            peer.close()
        assert all(peer.pipeline.get_state(0)[1] == peer.Gst.State.NULL for peer in peers)


async def main():
    await pair()
    await pair(passive=True)


asyncio.run(main())
