# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mikhail Nevskiy
"""Proposed message-cache retention (issue #86, MSG2-14 eviction): current
KEEP growth, the scratch fixture, and the eviction plan. Does not call a
production prune (there is none) and does not touch a real profile.
"""
import json
import os
import tempfile

from common import load, ok
from cache_retention_fixture import (
    CHATS_KEPT, apply_plan, build_scratch, is_local_message, iter_chat_files,
    local_message, plan_eviction, plan_trim, remote_message,
)

bm = load()


# --- current format and per-chat KEEP, against this tree (pinned main) ----------
assert bm.KEEP == 80 and bm.PAGE == 30
assert bm.PHOTO_DAYS == 30 and bm.DOCS_KEPT == 30
assert bm.CHATS.endswith(os.path.join("haltia-messenger", "chats"))
assert CHATS_KEPT == 200
folder = tempfile.mkdtemp(prefix="cache-retention-")
cache = bm.MessageCache(folder, delay=3600)
overflow = [remote_message(i, i, "t%d" % i) for i in range(bm.KEEP + 5)]
cache.add(7, overflow)
assert [m["id"] for m in cache.read(7)] == list(range(5, bm.KEEP + 5))
cache.flush()
path = cache._path(7)
assert os.path.isfile(path) and oct(os.stat(path).st_mode & 0o777) == "0o600"
with open(path) as fh:
    on_disk = json.load(fh)
assert isinstance(on_disk, list) and on_disk[0]["id"] == 5
assert cache._path("tg:9") == os.path.join(folder, "tg", "9.json")
# Today's add() drops an old unsent bubble once remote history fills KEEP.
mixed = [local_message(1, 1)] + overflow
cache.add(8, mixed)
assert not any(is_local_message(m) for m in cache.read(8))
assert plan_trim(mixed, bm.KEEP)[0]["id"] == "out-1"
assert [m["id"] for m in plan_trim(mixed, bm.KEEP) if not is_local_message(m)] == \
    list(range(5, bm.KEEP + 5))
ok("current KEEP and format")

# --- scratch fixture: growth, then a safe plan; production cache does not prune --
scratch_root = tempfile.mkdtemp(prefix="cache-retention-scratch-")
chats = os.path.join(scratch_root, "chats")
scratch_cache = bm.MessageCache(chats, delay=3600)
scratch = build_scratch(scratch_cache, chats, keep_files=3)
found = sorted((account, str(chat_id)) for chat_id, _path, account in iter_chat_files(chats))
assert found == [
    ("max", "101"), ("max", "102"), ("max", "103"), ("max", "104"),
    ("tg", "tg:201"), ("tg", "tg:202"),
]
assert os.path.isfile(scratch["list_path"]) and os.path.isfile(scratch["known_path"])
assert os.path.isfile(scratch["leftover_new"])
assert plan_eviction(chats, keep=3)["files_before"] == 6
assert plan_eviction(chats)["evict"] == []  # proposed CHATS_KEPT leaves a small tree
# Production MessageCache still has no file-count prune: everything stays.
assert sorted(os.path.basename(p) for p in scratch["old_max"]) == ["101.json", "102.json"]
for path in scratch["old_max"] + [scratch["recent_max"], scratch["old_tg"],
                                  scratch["recent_tg"], scratch["unsent_path"]]:
    assert os.path.isfile(path), path
ok("fixture growth")

plan = plan_eviction(chats, keep=scratch["keep_files"])
evicted = sorted(os.path.relpath(i["path"], chats) for i in plan["evict"])
kept = sorted(os.path.relpath(i["path"], chats) for i in plan["keep"])
protected = sorted(os.path.relpath(i["path"], chats) for i in plan["protected"])
assert evicted == ["101.json", "102.json", os.path.join("tg", "201.json")]
assert kept == ["103.json", "104.json", os.path.join("tg", "202.json")]
assert protected == ["104.json"]
assert plan["files_before"] == 6 and plan["files_after"] == 3
assert plan["bytes_after"] < plan["bytes_before"]
assert plan["skipped"] == []
# Ownership: a recent Telegram file stays, an old one of the same prefix goes.
assert any(i["account"] == "tg" for i in plan["keep"])
assert any(i["account"] == "tg" for i in plan["evict"])
assert any(i["account"] == "max" for i in plan["keep"])
# list.json is not a chat file; the leftover .new is not either.
assert scratch["list_path"] not in [i["path"] for i in plan["keep"] + plan["evict"]]
assert scratch["leftover_new"] not in [i["path"] for i in plan["keep"] + plan["evict"]]
ok("expected eviction plan")

# Applying the plan is allowed only on this scratch tree, and must spare
# unsent data, list.json, known.json and the other messenger's recent chat.
apply_plan(plan)
assert not os.path.exists(scratch["old_max"][0])
assert not os.path.exists(scratch["old_max"][1])
assert not os.path.exists(scratch["old_tg"])
assert os.path.isfile(scratch["recent_max"])
assert os.path.isfile(scratch["recent_tg"])
assert os.path.isfile(scratch["unsent_path"])
with open(scratch["unsent_path"]) as fh:
    left = json.load(fh)
assert any(is_local_message(m) for m in left)
assert os.path.isfile(scratch["list_path"])
with open(scratch["list_path"]) as fh:
    assert json.load(fh)[0]["id"] == 103
assert os.path.isfile(scratch["known_path"])
with open(scratch["known_path"]) as fh:
    assert json.load(fh) == [10, 20]
assert os.path.isfile(scratch["leftover_new"])
fresh = bm.MessageCache(chats, delay=3600)
assert fresh.read(103)[0]["text"] == "recent-max"
assert fresh.read("tg:202")[0]["text"] == "recent-tg"
assert fresh.read(101) == [] and fresh.read("tg:201") == []
assert any(is_local_message(m) for m in fresh.read(104))
ok("scratch apply preserves unsent and ownership")

# protect_ids keeps a remote file that would otherwise go; unreadable JSON
# is skipped, not deleted; DATA stays out of the walk.
protect_root = tempfile.mkdtemp(prefix="cache-retention-protect-")
protect_chats = os.path.join(protect_root, "chats")
protect_cache = bm.MessageCache(protect_chats, delay=3600)
built = build_scratch(protect_cache, protect_chats, keep_files=3)
broken = protect_cache._path(109)
with open(broken, "w") as fh:
    fh.write("{not json")
plan = plan_eviction(protect_chats, keep=3, protect_ids={101})
paths = {i["path"] for i in plan["evict"]}
assert built["old_max"][0] not in paths  # 101 protected by id
assert broken in plan["skipped"] and broken not in paths
assert built["known_path"] not in paths
assert os.path.isfile(built["known_path"])
ok("protect_ids and unreadable files")
print("cache retention ok")
