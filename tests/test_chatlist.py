# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2026 Mikhail Nevskiy
"""The chat list's rules, without the window or MAX: tabs and order, pins,
notifications, strangers, counts, the search, dialogs from the search, and
what it keeps on disk."""
import os

from common import load, ok

bm = load()
tmp = os.environ["HOME"]
LIST, PREFS = os.path.join(tmp, "list.json"), os.path.join(tmp, "chats.json")


def chat(cid, title, kind="DIALOG", t=0, unread=0, peer=None, stranger=False, last=""):
    return {"id": cid, "title": title, "type": kind, "last": last, "time": t, "unread": unread,
            "peer": peer, "stranger": stranger}


def ids(entries):
    return [e[0]["id"] for e in entries]


L = bm.ChatList(LIST, PREFS)
L.replace([chat(11, "Мама", t=50, unread=2, peer=10),
           chat(12, "Дача", "CHAT", t=90, unread=1),
           chat(13, "Спамер", t=99, unread=7, peer=30, stranger=True),
           chat(-31, "Новости", "CHANNEL", t=95, unread=4),
           chat(-32, "Погода", "CHANNEL", t=10, unread=3)])

# --- tabs and order: the newest first, channels apart, strangers hidden ----------
assert ids(L.entries("chats")) == [12, 11] and ids(L.entries("channels")) == [-31, -32]
assert L.counts() == {"chats": 3, "channels": 7, "loud": 3}
assert L.hidden(13) and not L.loud(13) and L.find("спам") == []
L.contacts_only = False
assert ids(L.entries("chats")) == [13, 12, 11] and L.counts()["loud"] == 10 and L.loud(13)
L.contacts_only = True
ok("tabs, order, strangers")

# --- pins: first, in the order pinned, and kept ------------------------------------
L.pin(11)
L.pin(12)
assert ids(L.entries("chats")) == [11, 12]
assert L.entries("chats")[0][1] is True and L.is_pinned(12)
L.pin(11)
assert ids(L.entries("chats")) == [12, 11]
assert bm.load_json(PREFS, {})["pinned"] == [12]
assert oct(os.stat(PREFS).st_mode & 0o777) == "0o600"
ok("pins")

# --- notifications: channels quiet unless switched on, others loud unless off ------
assert L.quiet(-31) and not L.loud(-31) and L.loud(11) and L.loud(999)  # unknown: loud
L.mute(-31)
assert L.loud(-31) and L.counts()["loud"] == 7
L.mute(11)
assert not L.loud(11) and L.entries("chats")[1][2] is True and L.counts()["loud"] == 5
assert bm.load_json(PREFS, {}) == {"pinned": [12], "muted": [11], "unmuted": [-31]}
L2 = bm.ChatList(LIST, PREFS)  # kept on disk
assert L2.loud(-31) and not L2.loud(11) and L2.is_pinned(12)
ok("notifications")

# --- what comes: a message, reading, a new chat, removing, renaming, contacts -------
L.update(chat(-32, "Погода", "CHANNEL", t=200, unread=4, last="Дождь"))
assert ids(L.entries("channels")) == [-32, -31] and L.get(-32)["last"] == "Дождь"
L.read(-32)
assert L.get(-32)["unread"] == 0
L.update(chat(14, "Новый", t=300, peer=40))
L.saving.join()  # written by a thread
assert 14 in [s["id"] for s in bm.load_json(LIST, [])]  # a new chat is kept at once
saved = L.saving
L.read(14)
L.update(dict(L.get(14)))  # nothing new: not written again
assert L.saving is saved
L.remove(14)
L.saving.join()
assert not L.listed(14) and 14 not in [s["id"] for s in bm.load_json(LIST, [])]
L.retitle(11, "Мамочка")
assert L.get(11)["title"] == "Мамочка" and L.find("мамоч")[0]["id"] == 11
L.known(30)
assert not L.hidden(13) and ids(L.entries("chats"))[:2] == [12, 13]  # 12 is pinned
ok("updates")

# --- a dialog from the search: not listed until written to ---------------------------
L.start_dialog(chat(41, "Ольга", peer=40))
assert L.get(41)["title"] == "Ольга" and not L.listed(41) and 41 not in ids(L.entries("chats"))
L.wrote(41, "Здравствуйте")
assert L.listed(41) and L.get(41)["last"] == "Вы: Здравствуйте" and 41 in ids(L.entries("chats"))
L.start_dialog(chat(11, "Мама"))  # already in the list: nothing changes
assert L.get(11)["title"] == "Мамочка"
ok("dialogs from the search")

# --- the list is there at once on the next start ----------------------------------------
L.saving.join()
L3 = bm.ChatList(LIST, PREFS)
assert {s["id"] for s in L3.chats.values()} == {11, 12, 13, -31, -32, 41}
assert oct(os.stat(LIST).st_mode & 0o777) == "0o600"
ok("kept list")

# --- one chat at a time, as the window asks: the same answers as entries() -----------------
for tab in ("chats", "channels"):
    want = ids(L.entries(tab))
    assert sorted((i for i in L.chats if L.shown(i, tab)), key=L.order) == want, tab
assert L.entry(12) == (L.get(12), L.is_pinned(12), L.quiet(12)) and L.entry(999) is None
ok("one chat's place")
