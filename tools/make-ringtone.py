# SPDX-License-Identifier: GPL-3.0-or-later
"""Render our own short, plucked call melody using only the standard library.

No recording, sample or note sequence from MAX is used. The resulting WAV
is shipped so ringing needs no synthesis on the tablet's GTK thread.
"""
import array
import math
from pathlib import Path
import sys
import wave

RATE = 24000
DURATION = 4
# Two contrasting four-note phrases, followed by a quiet pause.
NOTES = ((0., 440.), (.22, 659.255), (.44, 554.365), (.66, 493.883),
         (1.15, 391.995), (1.37, 587.330), (1.59, 493.883), (1.81, 440.))


def render(path):
    samples = [0.] * (RATE * DURATION)
    for onset, frequency in NOTES:
        offset = round(onset * RATE)
        for n in range(round(.8 * RATE)):
            t = n / RATE
            phase = 2 * math.pi * frequency * t
            attack = min(1., t / .008)
            envelope = attack * math.exp(-t / .20) * min(1., (.8 - t) / .025)
            tone = (math.sin(phase) + .12 * math.sin(phase / 2)
                    + .35 * math.exp(-t / .13) * math.sin(phase * 2)
                    + .16 * math.exp(-t / .07) * math.sin(phase * 3))
            samples[offset + n] += tone * envelope
    peak = max(abs(value) for value in samples)
    pcm = array.array("h", (round(value / peak * .70 * 32767) for value in samples))
    if sys.byteorder != "little":
        pcm.byteswap()
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(RATE)
        output.writeframes(pcm.tobytes())


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "data/ringtone.wav"
    render(target)
