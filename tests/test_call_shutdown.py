# SPDX-License-Identifier: GPL-3.0-or-later
"""Real GTK quit with a backend send that never finishes: bounded shutdown."""
import asyncio
import json
import time
from common import load, ok
bm = load()
from fake_link import FakeLink
from fake_logind import FakeLogind
from gi.repository import GLib


class SilentSocket:
    attempted = None
    send_started = None
    async def send(self, raw):
        self.send_started = time.monotonic()
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
logind = FakeLogind()
app.call_logind.inhibit = logind.inhibit
app.set_flags(app.get_flags() | bm.Gio.ApplicationFlags.NON_UNIQUE)
socket, audio = SilentSocket(), Audio()
started = []
errors = []


async def setup():
    call = app.backend.accounts["max"].new_call("quit-timeout", 10, False)
    call.accepted = True
    call.socket, call.audio = socket, audio
    asyncio.create_task(call.end("HUNGUP"))
    while socket.attempted is None:
        await asyncio.sleep(.001)
    assert app.backend.accounts["max"].call is None
    assert call in app.backend.accounts["max"].ending_calls


def ready(_result, error):
    if error is not None:
        errors.append(error)
    app.call_logind.hold()
    assert not logind.released()
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
finished = time.monotonic()
assert not errors, errors
assert started and finished - started[0] < 3.5
assert socket.send_started is not None and 1.8 <= finished - socket.send_started < 3.5
assert audio.closed and socket.attempted["reason"] == "HUNGUP"
assert app.call_logind.fd is None and logind.released()
logind.close()
ok("GTK quit attempts HUNGUP, closes media and stops waiting after two seconds")
ok("quit releases the logind fd even when hangup cannot finish")
