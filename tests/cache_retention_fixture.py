# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mikhail Nevskiy
"""Scratch message-cache for the proposed retention policy (issue #86).

Builds a temporary CHATS tree in the current format, plans which chat files
a bounded pass would evict, and can apply that plan to the scratch tree.
Nothing here is imported by haltia-messenger, and it never looks at a real
profile: tests point it at a directory under the test HOME.
"""
import json
import os

# Proposed production cap (docs/cache-retention.md). Tests pass a smaller keep.
CHATS_KEPT = 200
PROTECTED_NAMES = {"list.json"}
LOCAL_STATES = {"sending", "failed"}


def is_local_message(msg):
    """Unsent / local-only: a queued bubble, not a messenger id."""
    if not isinstance(msg, dict):
        return False
    if msg.get("state") in LOCAL_STATES:
        return True
    mid = msg.get("id")
    return isinstance(mid, str) and mid.startswith("out-")


def plan_trim(msgs, keep):
    """Newest `keep` remote messages plus every local-only one, oldest first.

    Today's MessageCache.add keeps the newest KEEP by time and would drop an
    old unsent bubble; this is the trim the follow-up should use instead.
    """
    local, remote = [], []
    for msg in msgs:
        (local if is_local_message(msg) else remote).append(msg)
    remote.sort(key=lambda m: m.get("time") or 0)
    kept = local + remote[-keep:]
    kept.sort(key=lambda m: m.get("time") or 0)
    return kept


def iter_chat_files(folder):
    """Committed chat files: MAX `<id>.json`, another messenger `<prefix>/<id>.json`."""
    try:
        names = os.listdir(folder)
    except OSError:
        return
    for name in names:
        path = os.path.join(folder, name)
        if name in PROTECTED_NAMES or name.endswith(".new"):
            continue
        if name.endswith(".json") and os.path.isfile(path):
            stem = name[:-5]
            try:
                chat_id = int(stem)
            except ValueError:
                continue
            yield chat_id, path, "max"
            continue
        if not os.path.isdir(path) or os.path.islink(path):
            continue
        try:
            inner = os.listdir(path)
        except OSError:
            continue
        for inner_name in inner:
            if inner_name.endswith(".new") or not inner_name.endswith(".json"):
                continue
            fpath = os.path.join(path, inner_name)
            if os.path.isfile(fpath):
                yield "%s:%s" % (name, inner_name[:-5]), fpath, name


def _load_messages(path):
    try:
        with open(path) as fh:
            msgs = json.load(fh)
    except (OSError, ValueError):
        return None
    return msgs if isinstance(msgs, list) else None


def plan_eviction(folder, keep=CHATS_KEPT, protect_ids=()):
    """Which scratch chat files a bounded pass would drop. Deletes nothing.

    keep is the maximum number of chat files to leave. Protected files
    (list.json, local-only messages, protect_ids, unreadable JSON) always
    stay, even if that is more than keep. Among the rest, the oldest by
    mtime go until the cap is met or nothing unprotected remains.
    """
    protect_ids = set(protect_ids)
    protected, skipped, candidates = [], [], []
    for chat_id, path, account in iter_chat_files(folder):
        msgs = _load_messages(path)
        if msgs is None:
            skipped.append(path)
            continue
        info = {
            "chat_id": chat_id,
            "path": path,
            "account": account,
            "mtime": os.path.getmtime(path),
            "bytes": os.path.getsize(path),
            "messages": len(msgs),
        }
        local = any(is_local_message(m) for m in msgs)
        if chat_id in protect_ids or local:
            info["why"] = "local" if local else "protect_ids"
            protected.append(info)
        else:
            candidates.append(info)
    candidates.sort(key=lambda i: (i["mtime"], str(i["chat_id"])))
    room = max(0, keep - len(protected))
    evict = candidates[:max(0, len(candidates) - room)]
    kept = protected + candidates[len(evict):]
    bytes_before = sum(i["bytes"] for i in protected + candidates)
    bytes_after = sum(i["bytes"] for i in kept)
    return {
        "keep": kept,
        "evict": evict,
        "protected": protected,
        "skipped": skipped,
        "bytes_before": bytes_before,
        "bytes_after": bytes_after,
        "files_before": len(protected) + len(candidates),
        "files_after": len(kept),
    }


def apply_plan(plan):
    """Remove planned files in a scratch tree. Tests only; not a migration."""
    for info in plan["evict"]:
        try:
            os.remove(info["path"])
        except OSError:
            pass


def remote_message(msg_id, when, text="remote"):
    return {"id": msg_id, "time": when, "text": text, "chat": None, "sender": 1,
            "who": "", "photos": [], "mine": False, "reactions": [], "yours": None,
            "media": [], "forwarded": None}


def local_message(seq, when, text="не отправлено"):
    return {"id": "out-%d" % seq, "time": when, "text": text, "state": "failed",
            "chat": None, "sender": None, "who": "", "photos": [], "mine": True,
            "reactions": [], "yours": None, "media": [], "forwarded": None}


def build_scratch(cache, folder, keep_files=3):
    """A deterministic CHATS tree that outgrows `keep_files`.

    Six chat files: four MAX, two Telegram. One MAX file holds an unsent
    bubble. mtimes 1..4 on the old ones, 100 and 101 on the recent pair.
    list.json sits beside them; known.json lives *outside* folder.
    """
    os.makedirs(folder, exist_ok=True)
    cache.folder = folder
    rows = [
        (101, [remote_message(1, 10, "old-max-a")], 1),
        (102, [remote_message(1, 20, "old-max-b")], 2),
        (103, [remote_message(1, 30, "recent-max")], 100),
        ("tg:201", [remote_message(1, 40, "old-tg")], 4),
        ("tg:202", [remote_message(1, 50, "recent-tg")], 101),
    ]
    for chat_id, msgs, _mtime in rows:
        cache.add(chat_id, msgs)
    cache.flush()
    unsent_path = cache._path(104)
    os.makedirs(os.path.dirname(unsent_path), exist_ok=True)
    with open(unsent_path, "w") as fh:
        json.dump([remote_message(1, 5, "cached"), local_message(1, 6)],
                  fh, ensure_ascii=False)
    os.chmod(unsent_path, 0o600)
    for chat_id, _msgs, mtime in rows:
        os.utime(cache._path(chat_id), (mtime, mtime))
    os.utime(unsent_path, (3, 3))
    leftover = os.path.join(folder, "101.json.new")
    with open(leftover, "w") as fh:
        fh.write("[{}]")
    list_path = os.path.join(folder, "list.json")
    with open(list_path, "w") as fh:
        json.dump([{"id": 103, "title": "Недавний", "account": "max"}], fh)
    data_dir = os.path.join(os.path.dirname(folder), "data")
    os.makedirs(data_dir, exist_ok=True)
    known_path = os.path.join(data_dir, "known.json")
    with open(known_path, "w") as fh:
        json.dump([10, 20], fh)
    return {
        "folder": folder,
        "list_path": list_path,
        "known_path": known_path,
        "unsent_path": unsent_path,
        "leftover_new": leftover,
        "keep_files": keep_files,
        "old_max": [cache._path(101), cache._path(102)],
        "recent_max": cache._path(103),
        "old_tg": cache._path("tg:201"),
        "recent_tg": cache._path("tg:202"),
    }
