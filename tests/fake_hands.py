# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2026 Mikhail Nevskiy
"""Media's hands for tests (b8k-max's Media takes them at creation): they
record what would have been started, opened, fetched and played."""


class FakeHands:
    def __init__(self, photo_bytes=b""):
        self.spawned = []  # player command lines
        self.opened = []  # links given to the browser
        self.fetched = []  # (url, headers)
        self.photo_bytes = photo_bytes
        self.sound = None  # the FakePlayer, once made
        self.browser = True  # open_uri succeeds
        self.downloaded = []  # (url, headers) saved
        self.fail_download = False

    def spawn(self, cmd):
        self.spawned.append(cmd)

    def open_uri(self, url):
        self.opened.append(url)
        return self.browser

    def fetch(self, url, headers):
        self.fetched.append((url, dict(headers)))
        return self.photo_bytes

    def download(self, url, headers, path):
        self.downloaded.append((url, dict(headers)))
        if self.fail_download:
            raise OSError("connection reset")
        with open(path, "wb") as fh:
            fh.write(b"file from " + url.encode())

    def player(self, on_time, on_end):
        self.sound = FakePlayer(on_time, on_end)
        return self.sound


class FakePlayer:
    def __init__(self, on_time, on_end):
        self.on_time, self.on_end = on_time, on_end
        self.did = []  # ("play", url, agent), ("toggle",), ("stop",)
        self.playing = False

    def play(self, url, agent):
        self.did.append(("play", url, agent))
        self.playing = True

    def toggle(self):
        self.did.append(("toggle",))
        self.playing = not self.playing
        return self.playing

    def stop(self):
        self.did.append(("stop",))
        self.playing = False
