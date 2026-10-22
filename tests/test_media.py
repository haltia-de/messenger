# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mikhail Nevskiy
"""Media with fake hands, no network, no player: which links are let
through, the one header, redirects, the photo cache and its pruning, voice,
the player's command line, files, the log."""
import os
import array
import shutil
import sys
import tempfile
import time
import urllib.request
import wave
from unittest.mock import patch

from common import load, ok

bm = load()
from fake_hands import FakeHands  # noqa: E402
from gi.repository import GLib  # noqa: E402


def drain(sec=0.5):
    end = time.monotonic() + sec
    ctx = GLib.MainContext.default()
    while time.monotonic() < end:
        while ctx.iteration(False):
            pass
        time.sleep(0.01)


def log():
    try:
        return open(bm.LOG).read()
    except OSError:
        return ""


# --- the bundled call melody: audible phrases and a quiet loop boundary ----------
ringtone = bm.ringtone_file()
with wave.open(ringtone, "rb") as sound:
    assert sound.getnchannels() == 1 and sound.getsampwidth() == 2
    assert sound.getframerate() == 24000 and sound.getnframes() == 4 * 24000
    samples = array.array("h", sound.readframes(sound.getnframes()))
    if sys.byteorder != "little":
        samples.byteswap()
    assert 10000 < max(abs(sample) for sample in samples) < 32767
    assert any(samples[:24000]) and any(samples[24000:48000])
    assert not any(samples[-24000:])  # a pause before repeating; no splice click
with tempfile.TemporaryDirectory() as prefix:
    os.makedirs(os.path.join(prefix, "bin"))
    installed = os.path.join(prefix, "share", "haltia-messenger", "ringtone.wav")
    os.makedirs(os.path.dirname(installed))
    shutil.copyfile(ringtone, installed)
    with patch.object(bm, "__file__", os.path.join(prefix, "bin", "haltia-messenger")):
        assert bm.ringtone_file() == installed
ok("bundled ringtone PCM, headroom, phrases, quiet tail and installation-prefix lookup")


# --- which links: https on MAX's hosts only ------------------------------------------------
for good in ("https://vd.okcdn.ru/v.mp4", "https://i.oneme.ru/f", "https://x.mycdn.me/v",
             "https://max.ru/a"):
    assert bm.media_ok(good), good
for bad in ("http://i.oneme.ru/a", "https://192.168.1.1/a", "https://localhost/a",
            "file:///etc/passwd", "https://127.0.0.1/", "https://0x7f000001/a",
            "https://evil.com/a", "https://okcdn.ru.evil.com/a", "", None):
    assert not bm.media_ok(bad), bad
req = urllib.request.Request("https://i.oneme.ru/p.jpg")
redirect = bm.PhotoRedirect()
assert redirect.redirect_request(req, None, 302, "", {}, "https://evil.com/p.jpg") is None
assert redirect.redirect_request(req, None, 302, "", {}, "https://i2.oneme.ru/p.jpg") is not None
ok("hosts, redirects")

# --- photos: one header, cached, touched, pruned -----------------------------------------------
from gi.repository import GdkPixbuf  # noqa: E402
_pix = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 2, 2)
_pix.fill(0x3584e4ff)
png = _pix.save_to_bufferv("png", [], [])[1]
hands = FakeHands(photo_bytes=png)
media = bm.Media(hands.spawn, hands.open_uri, hands.fetch, hands.player)
media.agent = "Mozilla/5.0 (X11) Chrome/120"
got = []
media.photo("https://evil.com/p.png", got.append)
drain(0.2)
assert not hands.fetched and not got and "photo refused: evil.com/p.png" in log()
media.photo("https://i.oneme.ru/p.png?sig=SECRET", got.append)
drain()
assert hands.fetched == [("https://i.oneme.ru/p.png?sig=SECRET", {"User-Agent": media.agent})]
assert got and got[-1] is not None, (got, log())
cached = [n for n in os.listdir(bm.PHOTOS) if n.endswith(".img")]
assert len(cached) == 1
path = os.path.join(bm.PHOTOS, cached[0])
os.utime(path, (0, 0))
media.photo("https://i.oneme.ru/p.png?sig=SECRET", got.append)
drain()
assert len(hands.fetched) == 1 and os.path.getmtime(path) > time.time() - 60  # cached, touched
hands.photo_bytes = b"not a picture"
media.photo("https://i.oneme.ru/broken.png", got.append)
drain()
assert got[-1] is None and "photo i.oneme.ru/broken.png" in log()
old = os.path.join(bm.PHOTOS, "old.img")
open(old, "w").close()
os.utime(old, (0, 0))
os.makedirs(bm.CHATS, exist_ok=True)
media.prune()
assert not os.path.exists(old) and os.path.exists(path) and os.path.isdir(bm.CHATS)
ok("photos")

# --- the photo queue: two at a time, the last asked first, one fetch per link, none for the gone ---
import threading  # noqa: E402


class SlowHands(FakeHands):
    def __init__(self, data):
        super().__init__(photo_bytes=data)
        self.now = self.most = 0
        self.lock = threading.Lock()
        self.gate = threading.Event()  # fetches wait here till the test lets them go

    def fetch(self, url, headers):
        with self.lock:
            self.now += 1
            self.most = max(self.most, self.now)
        self.gate.wait(5)
        with self.lock:
            self.now -= 1
        return super().fetch(url, headers)


class Owner:
    gone = False


slow = SlowHands(png)
q = bm.Media(slow.spawn, slow.open_uri, slow.fetch, slow.player)
got = []
for name in ("a", "b"):  # these two keep both workers busy
    q.photo("https://i.oneme.ru/q-%s.png" % name, lambda pix, n=name: got.append(n))
time.sleep(0.2)
gone = Owner()
for name in ("c", "d", "e"):
    q.photo("https://i.oneme.ru/q-%s.png" % name, lambda pix, n=name: got.append(n),
            owner=gone if name == "d" else None)
q.photo("https://i.oneme.ru/q-e.png", lambda pix: got.append("e again"))  # the same link
gone.gone = True  # its bubble went before its turn
slow.gate.set()
drain(1.0)
fetched = [u.rsplit("-", 1)[1] for u, _h in slow.fetched]
assert slow.most == 2, slow.most
# both workers free at once take e and c together: their order is the threads'
assert sorted(fetched[:2]) == ["a.png", "b.png"] and sorted(fetched[2:]) == ["c.png", "e.png"]
assert sorted(got) == ["a", "b", "c", "e", "e again"]  # d's owner gone: not fetched, not told
ok("the photo queue")

# --- voice: one player, made once, with the agent ------------------------------------------------
assert not media.voice("https://evil.com/a.ogg") and hands.sound is None
assert media.voice("https://vd.okcdn.ru/a.ogg")
first = hands.sound
assert first.did == [("play", "https://vd.okcdn.ru/a.ogg", media.agent)]
assert media.voice("https://vd.okcdn.ru/b.ogg") and hands.sound is first
assert media.toggle() is False and media.toggle() is True
media.stop()
assert first.did[-1] == ("stop",)
times = []
media.on_time = lambda sec, total: times.append((sec, total))
first.on_time(2.0)
first.on_time(3.0, 200.0)  # a file's length comes from the player
assert times == [(2.0, None), (3.0, 200.0)]


def no_libmpv(on_time, on_end):
    raise OSError("libmpv.so: not found")


quiet = bm.Media(hands.spawn, hands.open_uri, hands.fetch, no_libmpv)
assert not quiet.voice("https://vd.okcdn.ru/a.ogg") and not quiet.voice("https://vd.okcdn.ru/a.ogg")
assert log().count("voice: no libmpv") == 1  # tried once
assert quiet.toggle() is False
quiet.stop()
ok("voice")

# --- video: the player's command line ---------------------------------------------------------
assert not media.video("https://evil.com/v.mp4", "Мама") and not hands.spawned
media.voice("https://vd.okcdn.ru/a.ogg")
assert media.video("https://vd.okcdn.ru/v.mp4?sig=SECRET", "Мама")
assert first.did[-1] == ("stop",)  # the voice stops for it
assert hands.spawned[-1] == ["mpv", "--fs", "--ytdl=no", "--load-unsafe-playlists=no",
                             "--user-agent=" + media.agent, "--", "https://vd.okcdn.ru/v.mp4?sig=SECRET"]
player = os.path.join(os.environ["HOME"], "haltia-vplay")
with open(player, "w") as fh:
    fh.write("#!/bin/sh\n")
os.chmod(player, 0o755)
bm.PLAYERS = (player,)
assert media.video("https://vd.okcdn.ru/v.mp4", "Мама")
cmd = hands.spawned[-1]
assert cmd[:4] == [player, "--title", "Мама", "https://vd.okcdn.ru/v.mp4"]
assert set(cmd[4:]) == {"ytdl=no", "load-unsafe-playlists=no", "user-agent=" + media.agent,
                        "terminal=yes", "msg-level=all=warn"}
assert not any("referrer" in a or "Origin" in a for c in hands.spawned for a in c)


def missing(cmd):
    raise OSError("no such file")


assert not bm.Media(missing, hands.open_uri, hands.fetch, hands.player).video(
    "https://vd.okcdn.ru/v.mp4", "x")
assert "video: no player" in log()
ok("video")

# --- files: fetched under their names, opened by the desktop's program for them -----------
opened = []
docs = bm.Media(hands.spawn, hands.open_uri, hands.fetch, hands.player, hands.download)
assert docs.file("https://fd.oneme.ru/f.pdf", "Договор.pdf", opened.append)
drain()
[doc] = [os.path.join(d, f) for d, _s, fs in os.walk(bm.DOCS) for f in fs]
assert os.path.basename(doc) == "Договор.pdf" and os.path.dirname(doc) != bm.DOCS
assert opened == [True] and hands.opened == [bm.GLib.filename_to_uri(doc)]
# another message's file of the same name: its own folder, the first left as it was
assert docs.file("https://fd.oneme.ru/other.pdf", "Договор.pdf", opened.append)
drain()
assert hands.opened[-1] != hands.opened[0] and open(doc, "rb").read() == b"file from https://fd.oneme.ru/f.pdf"
hands.opened.pop()
opened.pop()
assert not docs.file("https://evil.com/f.pdf", "x.pdf") and len(hands.opened) == 1
hands.browser = False  # nothing opens such a file
assert docs.file("https://fd.oneme.ru/g.pdf", "g.pdf", opened.append)
drain()
assert opened == [True, False]
hands.browser = True
# only documents, pictures and text are opened; never a .desktop file or a script
for name in ("ярлык.desktop", "скрипт.sh", "программа.exe", "без расширения"):
    assert not docs.file("https://fd.oneme.ru/x", name, opened.append), name
assert bm.openable("Отчёт.DOCX") and bm.openable("фото.jpg")
# DOCS bounded: the documents opened longest ago go
for k in range(bm.DOCS_KEPT + 5):
    os.makedirs(os.path.join(bm.DOCS, "old%02d" % k), exist_ok=True)
    os.utime(os.path.join(bm.DOCS, "old%02d" % k), (k, k))
assert docs.file("https://fd.oneme.ru/new.pdf", "Новый.pdf", opened.append)
drain()
left = os.listdir(bm.DOCS)
assert len(left) <= bm.DOCS_KEPT and "old00" not in left and opened[-1] is True
hands.downloaded.clear()
ok("files")

# --- saving: a harmless name, never over another, nothing left of a failure --------------
assert bm.safe_name("../../etc/passwd") == "passwd" and bm.safe_name(".bashrc") == "bashrc"
assert bm.safe_name("a\x00b\nc.mp3") == "abc.mp3" and bm.safe_name("") == "файл"
assert bm.safe_name("x" * 300).startswith("x") and len(bm.safe_name("x" * 300)) == 120
folder = os.path.join(os.environ["HOME"], "Загрузки", "MAX")
saver = bm.Media(hands.spawn, hands.open_uri, hands.fetch, hands.player, hands.download)
saver.agent = "Agent/1"
paths = []
saver.save("https://evil.com/x.pdf", folder, "x.pdf", paths.append)
drain(0.2)
assert paths == [None] and not hands.downloaded and "save refused: evil.com/x.pdf" in log()
for _ in range(2):
    saver.save("https://fd.oneme.ru/f.pdf?sig=SECRET", folder, "../Отчёт.pdf", paths.append)
drain()
assert sorted(os.listdir(folder)) == ["Отчёт (2).pdf", "Отчёт.pdf"], os.listdir(folder)
assert hands.downloaded[-1] == ("https://fd.oneme.ru/f.pdf?sig=SECRET", {"User-Agent": "Agent/1"})
assert open(os.path.join(folder, "Отчёт.pdf"), "rb").read().startswith(b"file from")
saver.save("https://fd.oneme.ru/new.pdf", folder, "Отчёт.pdf", paths.append, replace=True)
drain()
assert sorted(os.listdir(folder)) == ["Отчёт (2).pdf", "Отчёт.pdf"]  # written over, not numbered
assert open(os.path.join(folder, "Отчёт.pdf"), "rb").read() == b"file from https://fd.oneme.ru/new.pdf"
hands.fail_download = True
saver.save("https://fd.oneme.ru/x.pdf", folder, "Отчёт.pdf", paths.append, replace=True)
drain()
assert paths[-1] is None and os.path.exists(os.path.join(folder, "Отчёт.pdf"))  # a failure keeps the old
saver.save("https://fd.oneme.ru/g.pdf", folder, "g.pdf", paths.append)
drain()
assert paths[-1] is None and "g.pdf" not in os.listdir(folder) and "g.pdf.part" not in os.listdir(folder)
hands.fail_download = False
saver_downloads = list(hands.downloaded)
assert bm.default_folder().endswith(os.sep + "MAX")
ok("saving")

# --- another messenger's attachments: no link, fetched by its link (own) --------------------
owned = {}  # ref -> what its link fetches


def own(ref, path):
    if ref not in owned:
        raise LookupError("not there")
    with open(path, "wb") as fh:
        fh.write(owned[ref])


tgm = bm.Media(hands.spawn, hands.open_uri, hands.fetch, hands.player, hands.download)
got = []
tgm.photo("tg:photo:5:1", got.append)
drain(0.2)
assert not got and "photo refused: tg:photo:5:1" in log()  # no own hand: not fetched at all
tgm.own = own
owned.update({"tg:photo:5:1": png, "tg:voice:5:2": b"OggS", "tg:video:5:3": b"mp4",
              "tg:file:5:4": b"%PDF"})
for bad in ("file:///etc/passwd", "javascript:alert(1)", "http://i.oneme.ru/a", "tg"):
    assert tgm.how(bad) is None, bad
assert tgm.how("tg:photo:5:1") == "own" and tgm.how("https://i.oneme.ru/a") == "http"
n = len(hands.fetched)
tgm.photo("tg:photo:5:1", got.append)
drain()
assert got and got[0] is not None and len(hands.fetched) == n  # through own, not the web
assert tgm.voice("tg:voice:5:2")
drain()
played = hands.sound.did[-1]
assert played[0] == "play" and played[1].startswith(bm.PHOTOS) and open(played[1], "rb").read() == b"OggS"
ended = []
tgm.on_end = lambda: ended.append(1)
assert tgm.voice("tg:voice:5:9")  # its link cannot fetch it: told as an end
drain()
assert ended and hands.sound.did[-1] == ("stop",)
tgm.voice("tg:voice:5:2")
tgm.stop()  # stopped before it was there: it does not start after
drain()
assert hands.sound.did[-1] == ("stop",)
assert tgm.video("tg:video:5:3", "Мама")
drain()
cmd = hands.spawned[-1]
assert any(c.startswith(bm.PHOTOS) for c in cmd) and not any(c.startswith("tg:") for c in cmd)
assert tgm.file("tg:file:5:4", "Счёт.pdf")
drain()
assert hands.opened[-1].startswith(bm.GLib.filename_to_uri(bm.DOCS)) and hands.opened[-1].endswith(
    bm.GLib.filename_to_uri("/Счёт.pdf")[len("file://"):])
paths = []
tgm.save("tg:file:5:4", folder, "Договор.pdf", paths.append)
drain()
assert paths[-1] and open(paths[-1], "rb").read() == b"%PDF" and len(hands.downloaded) == len(saver_downloads)
ok("another messenger's attachments")

# --- the log: 600, links without their signatures ----------------------------------------------
assert oct(os.stat(bm.LOG).st_mode & 0o777) == "0o600"
assert "SECRET" not in log() and "video vd.okcdn.ru/v.mp4 via mpv" in log()
ok("log")
