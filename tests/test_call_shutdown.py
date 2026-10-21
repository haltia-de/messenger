# SPDX-License-Identifier: GPL-3.0-or-later
"""Real GTK quit with a backend send that never finishes: bounded shutdown."""
import asyncio
import json
import time
from common import load, ok
bm = load()
from fake_link import FakeLink
from gi.repository import GLib


class SilentSocket:
    attempted = None
    async def send(self, raw):
        self.attempted = json.loads(raw)
        await asyncio.Future()  # the network cannot make quitting wait forever
    async def close(self):
        pass


class Audio:
    closed = False
    def close(self):
        self.closed = True


fake = FakeLink(can={"calls"})
app = bm.Max(link=fake)
app.set_flags(app.get_flags() | bm.Gio.ApplicationFlags.NON_UNIQUE)
socket, audio = SilentSocket(), Audio()
started = []
errors = []


async def setup():
    call = bm.VoiceCall("quit-timeout", 10, False, lambda *_args: None)
    call.accepted = True
    call.socket, call.audio = socket, audio
    app.backend.accounts["max"].call = call


def ready(_result, error):
    if error is not None:
        errors.append(error)
    started.append(time.monotonic())
    app.activate_action("quit", None)


def prepare():
    if app.backend.loop is None or "max" not in app.backend.accounts:
        return True
    app.backend.run(setup(), ready)
    return False


def stuck():
    errors.append("quit did not finish")
    app.quit()
    return False


GLib.timeout_add(10, prepare)
GLib.timeout_add_seconds(10, stuck)
app.run([])
assert not errors, errors
assert started and 1.8 <= time.monotonic() - started[0] < 3.5
assert audio.closed and socket.attempted["reason"] == "HUNGUP"
ok("GTK quit attempts HUNGUP, closes media and stops waiting after two seconds")
