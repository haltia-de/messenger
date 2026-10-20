# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2026 Mikhail Nevskiy
"""How fast the window is, on the fake link with many chats: for the tablet,
where the numbers decide what is worth making faster. Not a test: it prints
times and asserts nothing. On a display of its own:

    sh tests/run.sh bench.py
    HALTIA_PYTHON=/usr/bin/python3 sh tests/run.sh bench.py   (an installed package's Python)

or straight on the desktop's display: python3 tests/bench.py

CHATS (200) chats; a burst of MESSAGES (100) incoming ones while the window
shows the list; opening chats of KEEP cached messages; a long channel paged
up. What it times: the window's own handlers (fill_list, incoming, open's
first part), how late a 10 ms ticker of the
window's main loop came (what a person feels as stutter), and the cache's
writes in the MAX thread."""
import os
import statistics
import sys
import time

from common import load

bm = load()
from fake_link import FakeLink, now_ms  # noqa: E402
from gi.repository import GLib  # noqa: E402

CHATS = int(os.environ.get("BENCH_CHATS", 200))
MESSAGES = int(os.environ.get("BENCH_MESSAGES", 100))
times = {}  # what -> [ms]


def timed(what, fn):
    def wrapper(*args, **kwargs):
        t = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            times.setdefault(what, []).append((time.perf_counter() - t) * 1000)
    return wrapper


def spin(sec=0.0):
    end = time.monotonic() + sec
    ctx = GLib.MainContext.default()
    while True:
        while ctx.iteration(False):
            pass
        if time.monotonic() >= end:
            break
        time.sleep(0.005)


def wait(cond, sec=120.0):
    end = time.monotonic() + sec
    while not cond():
        if time.monotonic() > end:
            sys.exit("bench: timed out")
        spin(0.01)


class Ticker:
    """A 10 ms timeout on the main loop: how late it came is the stutter."""
    def __init__(self, what):
        self.what, self.last, self.on = what, time.monotonic(), True
        GLib.timeout_add(10, self.tick)

    def tick(self):
        now = time.monotonic()
        times.setdefault(self.what, []).append(max(0.0, (now - self.last) * 1000 - 10))
        self.last = now
        return self.on

    def stop(self):
        self.on = False


# --- MAX: many chats, a few long ones ------------------------------------------------------
fake = FakeLink()
NOW = now_ms()
people = []
for i in range(CHATS):
    uid = 1000 + i
    fake.person(uid, "Человек %d" % i, contact=True)
    people.append(uid)
dialogs = []
for i, uid in enumerate(people[:CHATS * 3 // 4]):
    cid = fake.dialog(uid)
    dialogs.append(cid)
    for k in range(bm.KEEP if i < 20 else 3):
        fake.say(cid, "Сообщение %d от %d" % (k, uid), uid if k % 2 else None,
                 t=NOW - (i * 1000 + k) * 60000)
groups = []
for i in range(CHATS - len(dialogs)):
    cid = -(100 + i)
    fake.group(cid, "Группа %d" % i, kind="CHANNEL" if i % 3 == 0 else "CHAT",
               members=people[i:i + 5])
    groups.append(cid)
    fake.say(cid, "Новость %d" % i, people[i], t=NOW - (i + 5) * 3600000)
channel = groups[0]
for k in range(600):  # a long channel, paged up
    fake.say(channel, "Длинная новость №%d, о жизни города и погоде на завтра." % k,
             people[0], t=NOW - (600 - k) * 600000)
bm.save_json(bm.KNOWN, people)

app = bm.Max(link=fake)
app.set_flags(app.get_flags() | bm.Gio.ApplicationFlags.NON_UNIQUE)  # beside a running one
app.backend.cache.add = timed("cache add (MAX thread)", app.backend.cache.add)
app.notify = lambda msg: None  # no desktop notifications from a bench
app.badge = timed("badge", app.badge)
app.fill_list = timed("fill_list", app.fill_list)
app.incoming = timed("incoming (window's part)", app.incoming)
app.open = timed("open (window's part)", app.open)
shown = []
app.telemetry.chat_shown = lambda wait_ms, draw_ms: shown.append((wait_ms, draw_ms))
app.register(None)

# --- start ---------------------------------------------------------------------------------
t0 = time.perf_counter()
app.do_activate()
activated = (time.perf_counter() - t0) * 1000
wait(lambda: app.chatlist.chats and app.backend.online)
listed = (time.perf_counter() - t0) * 1000
spin(0.5)

# --- a burst of messages while the list is shown --------------------------------------------
ticker = Ticker("main loop late, during the burst")
for i in range(MESSAGES):
    fake.incoming(dialogs[i % len(dialogs)], "Новое %d" % i, people[i % len(dialogs)])
    spin(0.02)
wait(lambda: len(times.get("incoming (window's part)", [])) >= MESSAGES)
ticker.stop()
spin(0.3)

# --- opening chats ------------------------------------------------------------------------------
for cid in dialogs[:20]:
    app.open(cid)
    wait(lambda: len(shown) >= 1 and app.view is not None and not app.view.pending_new)
    spin(0.05)
    app.show_list()
    spin(0.05)
opened = list(shown)

# --- a long channel, scrolled up -----------------------------------------------------------------
app.open(channel)
spin(1.0)
adj = app.view.scroll.get_vadjustment()
ticker = Ticker("main loop late, scrolling up")
for _ in range(150):
    adj.set_value(max(0.0, adj.get_value() - 300))
    spin(0.03)
ticker.stop()
spin(0.5)


# --- the numbers ---------------------------------------------------------------------------------
def line(what, values):
    values = sorted(values)
    p95 = values[min(len(values) - 1, int(len(values) * 0.95))]
    print("%-36s n=%-5d median %7.1f  p95 %7.1f  max %7.1f ms" % (
        what, len(values), statistics.median(values), p95, values[-1]))


print("chats %d, burst %d, python %s" % (CHATS, MESSAGES, sys.version.split()[0]))
print("%-36s %7.1f ms" % ("do_activate", activated))
print("%-36s %7.1f ms" % ("start to the list from MAX", listed))
for what in sorted(times):
    line(what, times[what])
if opened:
    line("open: waited for MAX", [w for w, _d in opened])
    line("open: drawn after", [d for _w, d in opened])
