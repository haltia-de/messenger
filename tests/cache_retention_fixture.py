# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mikhail Nevskiy
"""Scratch message-cache for the proposed retention policy (issue #86).

Builds a temporary CHATS tree in the current format, plans which chat files
a bounded pass would evict, and can apply that plan to an *owned* scratch
tree. Nothing here is imported by haltia-messenger. It never looks at a
real profile: own_scratch itself accepts only a directory under the process
temporary area, and apply_plan refuses any other root.
"""
import json
import math
import os
import stat
import tempfile

# Proposed production cap (docs/cache-retention.md). Tests pass a smaller keep.
CHATS_KEPT = 200
# Directory names MessageCache._path uses for another messenger (prefix
# without the colon). Unknown prefixes are left untouched.
KNOWN_PREFIXES = {"tg"}
PROTECTED_NAMES = {"list.json"}
LOCAL_STATES = {"sending", "failed"}
SCRATCH_MARKER = ".cache-retention-scratch"
SCRATCH_TOKEN = "haltia-cache-retention-scratch\n"
# Present .accessed that is not a finite Unix time. Distinct from None
# (the file is absent: never opened). plan_eviction skips that chat.
STAMP_INVALID = object()


class ScratchGuardError(ValueError):
    """own_scratch or apply_plan refused the root or a path; nothing was deleted."""


def canonical_int_stem(stem):
    """True if stem is exactly str(int(stem)): what MessageCache._path writes.

    int() also accepts 007, +5 and 1_0; those files are not canonical and
    are left untouched.
    """
    if not isinstance(stem, str) or not stem:
        return False
    try:
        return str(int(stem)) == stem
    except (TypeError, ValueError):
        return False


def is_local_message(msg):
    """Unsent / local-only: a queued bubble, not a messenger id."""
    if not isinstance(msg, dict) or "id" not in msg:
        return False
    if msg.get("state") in LOCAL_STATES:
        return True
    mid = msg["id"]
    return isinstance(mid, str) and mid.startswith("out-")


def messages_readable(msgs):
    """Conservative chat-file shape: a list of dicts that each have id.

    Invalid JSON, a non-list, a list of non-dicts, or dicts without id are
    unknown format. On BASE, read/add raise on those; they are never evicted.
    """
    if not isinstance(msgs, list):
        return False
    for msg in msgs:
        if not isinstance(msg, dict) or "id" not in msg:
            return False
    return True


def plan_trim(msgs, keep):
    """Newest `keep` remote messages plus every local-only one, oldest first.

    Today's MessageCache.add keeps the newest KEEP by time and would drop an
    old unsent bubble; this is the trim the follow-up should use instead.
    """
    local, remote = [], []
    for msg in msgs:
        if not isinstance(msg, dict) or "id" not in msg:
            continue
        (local if is_local_message(msg) else remote).append(msg)
    remote.sort(key=lambda m: m.get("time") or 0)
    kept = local + remote[-keep:]
    kept.sort(key=lambda m: m.get("time") or 0)
    return kept


def _listdir(folder):
    try:
        return os.listdir(folder)
    except OSError:
        return []


def _orphan_stamp(path):
    """A .accessed file whose sibling .json is missing (drop left it)."""
    if not path.endswith(".accessed") or not os.path.isfile(path):
        return False
    sibling = path[:-len(".accessed")] + ".json"
    return not os.path.isfile(sibling)


def classify_tree(folder):
    """Canonical chat files, ignored paths, leftover .new, orphan stamps.

    Follows no symlink. A .accessed next to a present .json is the chat's
    stamp, not listed here. A .accessed with no sibling JSON is an orphan:
    this pass counts it and does not sweep it (same limit as leftover .new).
    """
    chats, ignored, orphan_new, orphan_stamps = [], [], [], []
    for name in _listdir(folder):
        path = os.path.join(folder, name)
        if name in PROTECTED_NAMES or name == SCRATCH_MARKER:
            continue
        if os.path.islink(path):
            ignored.append(path)
            continue
        if name.endswith(".new") and os.path.isfile(path):
            orphan_new.append(path)
            continue
        if name.endswith(".accessed"):
            if _orphan_stamp(path):
                orphan_stamps.append(path)
            continue
        if name.endswith(".json") and os.path.isfile(path):
            stem = name[:-5]
            if canonical_int_stem(stem):
                chats.append((int(stem), path, "max"))
            else:
                ignored.append(path)
            continue
        if os.path.isdir(path):
            if name not in KNOWN_PREFIXES:
                ignored.append(path)
                continue
            for inner_name in _listdir(path):
                fpath = os.path.join(path, inner_name)
                if os.path.islink(fpath):
                    ignored.append(fpath)
                    continue
                if inner_name.endswith(".new") and os.path.isfile(fpath):
                    orphan_new.append(fpath)
                    continue
                if inner_name.endswith(".accessed"):
                    if _orphan_stamp(fpath):
                        orphan_stamps.append(fpath)
                    continue
                if inner_name.endswith(".json") and os.path.isfile(fpath):
                    stem = inner_name[:-5]
                    if canonical_int_stem(stem):
                        chats.append(("%s:%s" % (name, stem), fpath, name))
                    else:
                        ignored.append(fpath)
                    continue
                if inner_name not in PROTECTED_NAMES and inner_name != SCRATCH_MARKER:
                    ignored.append(fpath)
            continue
        ignored.append(path)
    return chats, ignored, orphan_new, orphan_stamps


def iter_chat_files(folder):
    """Committed canonical chat files: MAX `<id>.json`, Telegram `tg/<id>.json`."""
    chats, _ignored, _new, _stamps = classify_tree(folder)
    for item in chats:
        yield item


def access_stamp_path(chat_path):
    if not chat_path.endswith(".json"):
        raise ValueError("not a chat file: %s" % chat_path)
    return chat_path[:-5] + ".accessed"


def read_access_stamp(path):
    """User-access time, None if never opened, or STAMP_INVALID if present junk.

    Absent file: migration default, never accessed. Present but unreadable,
    empty, non-numeric, NaN or ±Infinity: unknown metadata — fail closed
    (the chat is skipped, not ranked as never-opened). Not the JSON mtime;
    incoming flush rewrites mtime and must not move this stamp.
    """
    stamp = access_stamp_path(path)
    if not os.path.lexists(stamp):
        return None
    try:
        if os.path.islink(stamp):
            return STAMP_INVALID
        with open(stamp) as fh:
            text = fh.read().strip()
        value = float(text)
    except (OSError, TypeError, ValueError):
        return STAMP_INVALID
    if not math.isfinite(value):
        return STAMP_INVALID
    return value


def mark_accessed(path, when):
    """Record that the person opened this chat. Incoming writes do not call this."""
    when = float(when)
    if not math.isfinite(when):
        raise ValueError("access stamp must be a finite Unix time")
    stamp = access_stamp_path(path)
    fd = os.open(stamp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write("%.6f\n" % when)


def write_stamp_raw(path, text):
    """Write sibling stamp bytes as-is (malformed-stamp tests)."""
    stamp = access_stamp_path(path)
    fd = os.open(stamp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    return stamp


def _load_messages(path):
    try:
        with open(path) as fh:
            msgs = json.load(fh)
    except (OSError, ValueError):
        return None
    return msgs if messages_readable(msgs) else None


def _rank(info):
    # Never-accessed (None) sorts before any stamp: unopened files go first.
    stamp = info["accessed"] if info["accessed"] is not None else float("-inf")
    return (stamp, info["mtime"], str(info["chat_id"]))


def plan_eviction(folder, keep=CHATS_KEPT, protect_ids=()):
    """Which scratch chat files a bounded pass would drop. Deletes nothing.

    keep is the maximum number of *readable canonical* chat files with a
    usable stamp (absent or a finite number) to leave. Protected files
    (local-only messages, protect_ids) always stay, even if that is more
    than keep. Unreadable canonical files, and chats whose .accessed is
    present but not a finite number, are skipped (they stay, are counted,
    and can make the tree exceed keep). Unknown prefixes and non-canonical
    names are ignored and never evicted. Among unprotected readable files,
    the least recently accessed go until the cap is met or nothing
    unprotected remains. Ranking is the access stamp, then mtime, then
    chat id. Incoming writes move mtime only. Orphan stamps and leftover
    .new are counted and not swept.
    """
    protect_ids = set(protect_ids)
    chats, ignored, orphan_new, orphan_stamps = classify_tree(folder)
    protected, skipped, candidates = [], [], []
    for chat_id, path, account in chats:
        msgs = _load_messages(path)
        if msgs is None:
            skipped.append(path)
            continue
        accessed = read_access_stamp(path)
        if accessed is STAMP_INVALID:
            skipped.append(path)
            continue
        try:
            mtime = os.path.getmtime(path)
            nbytes = os.path.getsize(path)
        except OSError:
            skipped.append(path)
            continue
        info = {
            "chat_id": chat_id,
            "path": path,
            "account": account,
            "mtime": mtime,
            "accessed": accessed,
            "bytes": nbytes,
            "messages": len(msgs),
        }
        local = any(is_local_message(m) for m in msgs)
        if chat_id in protect_ids or local:
            info["why"] = "local" if local else "protect_ids"
            protected.append(info)
        else:
            candidates.append(info)
    candidates.sort(key=_rank)
    room = max(0, keep - len(protected))
    evict = candidates[:max(0, len(candidates) - room)]
    kept = protected + candidates[len(evict):]
    bytes_before = sum(i["bytes"] for i in protected + candidates)
    bytes_after = sum(i["bytes"] for i in kept)
    files_after = len(kept)
    return {
        "keep": kept,
        "evict": evict,
        "protected": protected,
        "skipped": skipped,
        "ignored": ignored,
        "orphan_new": orphan_new,
        "orphan_stamps": orphan_stamps,
        "bytes_before": bytes_before,
        "bytes_after": bytes_after,
        "files_before": len(protected) + len(candidates),
        "files_after": files_after,
        "skipped_count": len(skipped),
        "ignored_count": len(ignored),
        "orphan_new_count": len(orphan_new),
        "orphan_stamp_count": len(orphan_stamps),
        # Readable kept files may already exceed keep (protected). Skipped
        # files stay on disk on top of that: the cap is not a byte bound
        # and not a hard file-count of the directory.
        "over_cap": (files_after + len(skipped)) > keep,
    }


def own_scratch(root):
    """Mark a directory under the process temp dir as apply_plan's only tree.

    Refuses a symlink and any path whose resolved location is outside
    tempfile.gettempdir(), and does not create that path. Not a general
    sandbox: only this fixture's deletion guard.
    """
    if not root:
        raise ScratchGuardError("scratch root is required")
    tmp = os.path.realpath(tempfile.gettempdir())
    if os.path.lexists(root) and _is_link(root):
        raise ScratchGuardError("scratch root is a symlink")
    if not _under(root, tmp):
        raise ScratchGuardError("scratch root is not a temporary directory")
    os.makedirs(root, exist_ok=True)
    if _is_link(root) or not os.path.isdir(root) or not _under(root, tmp):
        raise ScratchGuardError("scratch root is not a temporary directory")
    marker = os.path.join(root, SCRATCH_MARKER)
    fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(SCRATCH_TOKEN)
    return root


def _is_link(path):
    try:
        return stat.S_ISLNK(os.lstat(path).st_mode)
    except OSError:
        return False


def _under(path, root):
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root + os.sep)


def _require_scratch_root(scratch_root):
    if not scratch_root:
        raise ScratchGuardError("scratch root is required")
    if _is_link(scratch_root) or not os.path.isdir(scratch_root):
        raise ScratchGuardError("scratch root is not a directory: %s" % scratch_root)
    tmp = os.path.realpath(tempfile.gettempdir())
    if not _under(scratch_root, tmp):
        raise ScratchGuardError("scratch root is not a temporary directory")
    marker = os.path.join(scratch_root, SCRATCH_MARKER)
    if _is_link(marker) or not os.path.isfile(marker):
        raise ScratchGuardError("scratch root is not owned")
    try:
        with open(marker) as fh:
            token = fh.read()
    except OSError as exc:
        raise ScratchGuardError("scratch marker unreadable") from exc
    if token != SCRATCH_TOKEN:
        raise ScratchGuardError("scratch root is not owned")
    return os.path.realpath(scratch_root)


def _check_deletable(path, root):
    if _is_link(path):
        raise ScratchGuardError("refusing symlink: %s" % path)
    try:
        mode = os.lstat(path).st_mode
    except OSError as exc:
        raise ScratchGuardError("refusing missing path: %s" % path) from exc
    if not stat.S_ISREG(mode):
        raise ScratchGuardError("refusing non-file: %s" % path)
    if not _under(path, root):
        raise ScratchGuardError("refusing path outside scratch: %s" % path)
    name = os.path.basename(path)
    if name == SCRATCH_MARKER or name in PROTECTED_NAMES:
        raise ScratchGuardError("refusing protected name: %s" % path)


def apply_plan(plan, scratch_root):
    """Remove planned files only under an owned scratch root. Tests only.

    scratch_root must be a real directory this module marked, under the
    process temp dir. Every evict path must be a regular file inside it.
    Symlinks, foreign paths and a missing marker refuse the whole plan;
    nothing is deleted. Not a migration.
    """
    root = _require_scratch_root(scratch_root)
    targets = []
    for info in plan["evict"]:
        path = info["path"]
        _check_deletable(path, root)
        targets.append(path)
        stamp = access_stamp_path(path) if path.endswith(".json") else None
        if stamp and os.path.lexists(stamp):
            _check_deletable(stamp, root)
            targets.append(stamp)
    for path in targets:
        try:
            os.remove(path)
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
    No access stamps: they rank as never accessed, so order among them is
    mtime (the migration default). list.json sits beside them; known.json
    lives *outside* folder. The folder is marked so apply_plan may use it.
    """
    own_scratch(folder)
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
    decoy_path = os.path.join(data_dir, "999.json")
    with open(decoy_path, "w") as fh:
        json.dump([remote_message(1, 1, "data-decoy")], fh)
    return {
        "folder": folder,
        "list_path": list_path,
        "known_path": known_path,
        "decoy_path": decoy_path,
        "unsent_path": unsent_path,
        "leftover_new": leftover,
        "keep_files": keep_files,
        "old_max": [cache._path(101), cache._path(102)],
        "recent_max": cache._path(103),
        "old_tg": cache._path("tg:201"),
        "recent_tg": cache._path("tg:202"),
    }


def build_access_scratch(cache, folder):
    """Quiet user-accessed chat vs a noisy unopened channel.

    Chat 1 was opened (access stamp 50). Channel 2 was never opened.
    Incoming messages go through the production MessageCache.add and flush
    (not a helper that leaves the stamp alone by construction). After those
    writes the stamp on chat 1 is unchanged; mtimes are then set so a
    write-mtime LRU would keep the channel. The access-stamp policy keeps
    the quiet chat.
    """
    own_scratch(folder)
    cache.folder = folder
    cache.add(1, [remote_message(1, 10, "quiet-personal")])
    cache.add(2, [remote_message(1, 20, "noisy-channel")])
    cache.flush()
    quiet_path, noisy_path = cache._path(1), cache._path(2)
    mark_accessed(quiet_path, 50)
    stamp_path = access_stamp_path(quiet_path)
    with open(stamp_path) as fh:
        stamp_text = fh.read()
    stamp_mtime = os.path.getmtime(stamp_path)
    cache.add(1, [remote_message(2, 11, "quiet-later")])
    for step in range(3):
        cache.add(2, [remote_message(step + 2, 30 + step, "incoming-%d" % step)])
    cache.flush()
    os.utime(quiet_path, (10, 10))
    os.utime(noisy_path, (200, 200))
    return {
        "folder": folder,
        "quiet_path": quiet_path,
        "noisy_path": noisy_path,
        "stamp_path": stamp_path,
        "stamp_text": stamp_text,
        "stamp_mtime": stamp_mtime,
    }
