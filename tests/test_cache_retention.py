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
    CHATS_KEPT, KNOWN_PREFIXES, STAMP_INVALID, ScratchGuardError,
    access_stamp_path, apply_plan, build_access_scratch, build_scratch,
    canonical_int_stem, classify_tree, is_local_message, iter_chat_files,
    local_message, mark_accessed, messages_readable, own_scratch, plan_eviction,
    plan_trim, read_access_stamp, remote_message, write_stamp_raw,
)

bm = load()


def rels(folder, infos):
    return sorted(os.path.relpath(i["path"], folder) for i in infos)


# --- current format and per-chat KEEP, against this tree (pinned main) ----------
assert bm.KEEP == 80 and bm.PAGE == 30
assert bm.PHOTO_DAYS == 30 and bm.DOCS_KEPT == 30
assert bm.CHATS.endswith(os.path.join("haltia-messenger", "chats"))
assert CHATS_KEPT == 200 and KNOWN_PREFIXES == {"tg"}
assert canonical_int_stem("101") and canonical_int_stem("-100123")
assert canonical_int_stem("0")
assert not canonical_int_stem("007")
assert not canonical_int_stem("+5")
assert not canonical_int_stem("1_0")
assert not canonical_int_stem("tg")
assert messages_readable([{"id": 1}])
assert not messages_readable({"id": 1})
assert not messages_readable([1, 2])
assert not messages_readable([{"text": "no id"}])
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
assert cache._path("tg:-100123") == os.path.join(folder, "tg", "-100123.json")
assert not hasattr(bm.MessageCache, "prune")
# BASE flush rewrites mtime, so write-mtime cannot be least-recently-accessed.
os.utime(path, (1, 1))
cache.add(7, [remote_message(99, 99, "newer")])
cache.flush()
assert os.path.getmtime(path) > 1
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
assert os.path.isfile(scratch["leftover_new"]) and os.path.isfile(scratch["decoy_path"])
assert plan_eviction(chats, keep=3)["files_before"] == 6
assert plan_eviction(chats)["evict"] == []  # proposed CHATS_KEPT leaves a small tree
# Production MessageCache still has no file-count prune: everything stays.
assert sorted(os.path.basename(p) for p in scratch["old_max"]) == ["101.json", "102.json"]
for path in scratch["old_max"] + [scratch["recent_max"], scratch["old_tg"],
                                  scratch["recent_tg"], scratch["unsent_path"]]:
    assert os.path.isfile(path), path
ok("fixture growth")

plan = plan_eviction(chats, keep=scratch["keep_files"])
evicted = rels(chats, plan["evict"])
kept = rels(chats, plan["keep"])
protected = rels(chats, plan["protected"])
assert evicted == ["101.json", "102.json", os.path.join("tg", "201.json")]
assert kept == ["103.json", "104.json", os.path.join("tg", "202.json")]
assert protected == ["104.json"]
assert plan["files_before"] == 6 and plan["files_after"] == 3
assert plan["bytes_after"] < plan["bytes_before"]
assert plan["skipped"] == [] and plan["skipped_count"] == 0
assert plan["orphan_new"] == [scratch["leftover_new"]]
assert plan["orphan_new_count"] == 1
assert plan["orphan_stamps"] == [] and plan["orphan_stamp_count"] == 0
# Ownership: a recent Telegram file stays, an old one of the same prefix goes.
assert any(i["account"] == "tg" for i in plan["keep"])
assert any(i["account"] == "tg" for i in plan["evict"])
assert any(i["account"] == "max" for i in plan["keep"])
# list.json is not a chat file; the leftover .new is not either.
assert scratch["list_path"] not in [i["path"] for i in plan["keep"] + plan["evict"]]
assert scratch["leftover_new"] not in [i["path"] for i in plan["keep"] + plan["evict"]]
# DATA lives outside CHATS: the walk never yields it, the decoy is not planned.
plan_paths = ([i["path"] for i in plan["keep"] + plan["evict"]]
              + plan["skipped"] + plan["ignored"] + plan["orphan_new"]
              + plan["orphan_stamps"])
assert all(os.path.realpath(p).startswith(os.path.realpath(chats) + os.sep)
           for p in plan_paths)
assert scratch["known_path"] not in plan_paths
assert scratch["decoy_path"] not in plan_paths
assert os.path.dirname(os.path.realpath(scratch["known_path"])) != os.path.realpath(chats)
assert not os.path.realpath(scratch["known_path"]).startswith(os.path.realpath(chats) + os.sep)
assert not os.path.realpath(scratch["decoy_path"]).startswith(os.path.realpath(chats) + os.sep)
# Walking the parent, DATA and chats are unknown prefixes, not walked for files.
parent_plan = plan_eviction(scratch_root, keep=3)
parent_paths = ([i["path"] for i in parent_plan["keep"] + parent_plan["evict"]]
                + parent_plan["skipped"] + parent_plan["ignored"]
                + parent_plan["orphan_new"] + parent_plan["orphan_stamps"])
assert parent_plan["keep"] == [] and parent_plan["evict"] == []
assert chats in parent_plan["ignored"]
assert os.path.join(scratch_root, "data") in parent_plan["ignored"]
assert scratch["known_path"] not in parent_paths
assert scratch["decoy_path"] not in parent_paths
assert scratch["recent_max"] not in parent_paths
ok("expected eviction plan")

# Applying the plan is allowed only on this owned scratch tree, and must spare
# unsent data, list.json, known.json, the DATA decoy and the other messenger's
# recent chat. The leftover .new stays (orphan limit).
apply_plan(plan, chats)
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
assert os.path.isfile(scratch["decoy_path"])
with open(scratch["decoy_path"]) as fh:
    assert json.load(fh)[0]["text"] == "data-decoy"
assert os.path.isfile(scratch["leftover_new"])
fresh = bm.MessageCache(chats, delay=3600)
assert fresh.read(103)[0]["text"] == "recent-max"
assert fresh.read("tg:202")[0]["text"] == "recent-tg"
assert fresh.read(101) == [] and fresh.read("tg:201") == []
assert any(is_local_message(m) for m in fresh.read(104))
ok("scratch apply preserves unsent and ownership")

# --- access stamp: production add/flush must not move it. Incoming writes
# to an unopened channel do not outrank a user-accessed quiet chat.
# Write-mtime LRU would keep the channel. -----------------------------------
access_root = tempfile.mkdtemp(prefix="cache-retention-access-")
access_chats = os.path.join(access_root, "chats")
access_cache = bm.MessageCache(access_chats, delay=3600)
access = build_access_scratch(access_cache, access_chats)
with open(access["stamp_path"]) as fh:
    assert fh.read() == access["stamp_text"] == "50.000000\n"
assert os.path.getmtime(access["stamp_path"]) == access["stamp_mtime"]
assert read_access_stamp(access["quiet_path"]) == 50
assert read_access_stamp(access["noisy_path"]) is None
assert not os.path.exists(access_stamp_path(access["noisy_path"]))
assert os.path.getmtime(access["noisy_path"]) > os.path.getmtime(access["quiet_path"])
assert os.path.getmtime(access["noisy_path"]) >= 200
plan = plan_eviction(access_chats, keep=1)
assert rels(access_chats, plan["evict"]) == ["2.json"]
assert rels(access_chats, plan["keep"]) == ["1.json"]
assert plan["keep"][0]["accessed"] == 50
assert plan["evict"][0]["accessed"] is None
apply_plan(plan, access_chats)
assert os.path.isfile(access["quiet_path"])
assert os.path.isfile(access["stamp_path"])
assert not os.path.exists(access["noisy_path"])
ok("access stamp survives add/flush and beats incoming writes")

# --- protected files may exceed CHATS_KEPT; room is 0; exact evict set ------
over_root = tempfile.mkdtemp(prefix="cache-retention-overcap-")
over_chats = os.path.join(over_root, "chats")
over_cache = bm.MessageCache(over_chats, delay=3600)
over = build_scratch(over_cache, over_chats, keep_files=1)
plan = plan_eviction(over_chats, keep=1)
# 104 is local-only; keep=1 → room 0 → every unprotected file goes.
assert rels(over_chats, plan["protected"]) == ["104.json"]
assert plan["files_after"] == 1 and plan["over_cap"] is False
assert rels(over_chats, plan["evict"]) == [
    "101.json", "102.json", "103.json", os.path.join("tg", "201.json"),
    os.path.join("tg", "202.json"),
]
# Two protected and keep=1: the cap is already exceeded by protected files.
plan = plan_eviction(over_chats, keep=1, protect_ids={101})
assert rels(over_chats, plan["protected"]) == ["101.json", "104.json"]
assert plan["files_after"] == 2 and plan["over_cap"] is True
assert rels(over_chats, plan["evict"]) == [
    "102.json", "103.json", os.path.join("tg", "201.json"),
    os.path.join("tg", "202.json"),
]
# Two protected, keep=2: still room 0.
plan = plan_eviction(over_chats, keep=2, protect_ids={101})
assert rels(over_chats, plan["protected"]) == ["101.json", "104.json"]
assert plan["files_after"] == 2
assert rels(over_chats, plan["evict"]) == [
    "102.json", "103.json", os.path.join("tg", "201.json"),
    os.path.join("tg", "202.json"),
]
# keep=3, protect 101: protected {101, 104}, room 1, newest unstamped is tg/202.
plan = plan_eviction(over_chats, keep=3, protect_ids={101})
assert rels(over_chats, plan["protected"]) == ["101.json", "104.json"]
assert rels(over_chats, plan["keep"]) == [
    "101.json", "104.json", os.path.join("tg", "202.json"),
]
assert rels(over_chats, plan["evict"]) == [
    "102.json", "103.json", os.path.join("tg", "201.json"),
]
ok("protected over cap and exact eviction sets")

# --- unreadable / unknown shape skipped; skipped counted; DATA not in walk --
protect_root = tempfile.mkdtemp(prefix="cache-retention-protect-")
protect_chats = os.path.join(protect_root, "chats")
protect_cache = bm.MessageCache(protect_chats, delay=3600)
built = build_scratch(protect_cache, protect_chats, keep_files=3)
broken = protect_cache._path(109)
with open(broken, "w") as fh:
    fh.write("{not json")
non_dicts = protect_cache._path(110)
with open(non_dicts, "w") as fh:
    json.dump([1, 2, 3], fh)
no_id = protect_cache._path(111)
with open(no_id, "w") as fh:
    json.dump([{"text": "no id"}], fh)
not_list = protect_cache._path(112)
with open(not_list, "w") as fh:
    json.dump({"id": 1}, fh)
plan = plan_eviction(protect_chats, keep=3, protect_ids={101})
paths = {i["path"] for i in plan["evict"]}
assert built["old_max"][0] not in paths  # 101 protected by id
assert broken in plan["skipped"] and broken not in paths
assert non_dicts in plan["skipped"] and non_dicts not in paths
assert no_id in plan["skipped"] and no_id not in paths
assert not_list in plan["skipped"] and not_list not in paths
assert plan["skipped_count"] == 4
# Cap is on readable files; skipped stay and the tree can exceed keep.
assert plan["over_cap"] is True
assert plan["files_before"] == 6  # six readable canonical chats
assert 109 not in [i["chat_id"] for i in plan["keep"] + plan["evict"]]
all_planned = (list(paths) + [i["path"] for i in plan["keep"]]
               + plan["skipped"] + plan["ignored"] + plan["orphan_new"]
               + plan["orphan_stamps"])
assert built["known_path"] not in all_planned
assert built["decoy_path"] not in all_planned
assert os.path.isfile(built["known_path"]) and os.path.isfile(built["decoy_path"])
# All planned paths stay under chats/, never under DATA.
for p in all_planned:
    assert os.path.realpath(p).startswith(os.path.realpath(protect_chats) + os.sep)
assert not os.path.realpath(built["known_path"]).startswith(
    os.path.realpath(protect_chats) + os.sep)
assert not os.path.realpath(built["decoy_path"]).startswith(
    os.path.realpath(protect_chats) + os.sep)
# Parent walk: DATA and chats are unknown prefixes, files inside are unseen.
parent = os.path.dirname(protect_chats)
parent_plan = plan_eviction(parent, keep=3)
parent_all = ([i["path"] for i in parent_plan["keep"] + parent_plan["evict"]]
              + parent_plan["skipped"] + parent_plan["ignored"]
              + parent_plan["orphan_new"] + parent_plan["orphan_stamps"])
assert parent_plan["keep"] == [] and parent_plan["evict"] == []
assert protect_chats in parent_plan["ignored"]
assert os.path.join(parent, "data") in parent_plan["ignored"]
assert built["known_path"] not in parent_all
assert built["decoy_path"] not in parent_all
ok("protect_ids, unreadable shape, DATA sentinel")

# --- unknown prefixes and non-canonical ids are left untouched --------------
shape_root = tempfile.mkdtemp(prefix="cache-retention-shape-")
shape_chats = os.path.join(shape_root, "chats")
shape_cache = bm.MessageCache(shape_chats, delay=3600)
shape = build_scratch(shape_cache, shape_chats, keep_files=3)
weird = [
    os.path.join(shape_chats, "007.json"),
    os.path.join(shape_chats, "+5.json"),
    os.path.join(shape_chats, "1_0.json"),
]
for path, stem_text in zip(weird, ("007", "+5", "1_0")):
    with open(path, "w") as fh:
        json.dump([remote_message(1, 1, stem_text)], fh)
foreign_dir = os.path.join(shape_chats, "other")
os.makedirs(foreign_dir)
foreign = os.path.join(foreign_dir, "1.json")
with open(foreign, "w") as fh:
    json.dump([remote_message(1, 1, "foreign")], fh)
tg_bad = os.path.join(shape_chats, "tg", "007.json")
with open(tg_bad, "w") as fh:
    json.dump([remote_message(1, 1, "tg-007")], fh)
tg_neg = os.path.join(shape_chats, "tg", "-100123.json")
with open(tg_neg, "w") as fh:
    json.dump([remote_message(1, 1, "tg-channel")], fh)
os.utime(tg_neg, (0, 0))  # oldest; would go if counted
plan = plan_eviction(shape_chats, keep=3)
ignored = set(plan["ignored"])
for path in weird + [foreign_dir, tg_bad]:
    assert path in ignored, path
assert foreign_dir in ignored  # unknown prefix: the directory, not walked for eviction
found_ids = {i["chat_id"] for i in plan["keep"] + plan["evict"]}
assert "tg:-100123" in found_ids  # canonical negative Telegram id
assert 7 not in found_ids and "+5" not in found_ids
apply_plan(plan, shape_chats)
for path in weird + [foreign, tg_bad]:
    assert os.path.isfile(path), path
assert os.path.isdir(foreign_dir)
ok("unknown prefixes and canonical ids")

# --- apply_plan refuses outside, symlink and foreign paths; deletes nothing --
guard_root = tempfile.mkdtemp(prefix="cache-retention-guard-")
guard_chats = os.path.join(guard_root, "chats")
guard_cache = bm.MessageCache(guard_chats, delay=3600)
guard = build_scratch(guard_cache, guard_chats, keep_files=3)
good = plan_eviction(guard_chats, keep=3)
outside_dir = tempfile.mkdtemp(prefix="cache-retention-outside-")
outside = os.path.join(outside_dir, "101.json")
with open(outside, "w") as fh:
    json.dump([remote_message(1, 1, "outside")], fh)
# Foreign path mixed into an otherwise valid plan: refuse, evict targets stay.
mixed_plan = dict(good)
mixed_plan["evict"] = list(good["evict"]) + [{"path": outside}]
try:
    apply_plan(mixed_plan, guard_chats)
    raise AssertionError("apply_plan accepted a path outside the scratch root")
except ScratchGuardError:
    pass
assert os.path.isfile(outside)
for info in good["evict"]:
    assert os.path.isfile(info["path"]), info["path"]
# Symlink to an outside victim, named like a canonical chat.
victim = os.path.join(outside_dir, "victim.json")
with open(victim, "w") as fh:
    json.dump([remote_message(1, 1, "victim")], fh)
link = os.path.join(guard_chats, "888.json")
os.symlink(victim, link)
_chats, ignored, _new, _stamps = classify_tree(guard_chats)
assert link in ignored
assert 888 not in [cid for cid, _p, _a in iter_chat_files(guard_chats)]
link_plan = {"evict": [{"path": link}]}
try:
    apply_plan(link_plan, guard_chats)
    raise AssertionError("apply_plan accepted a symlink")
except ScratchGuardError:
    pass
assert os.path.isfile(victim) and os.path.islink(link)
# Unowned foreign tree: no marker.
foreign_root = tempfile.mkdtemp(prefix="cache-retention-foreign-")
foreign_file = os.path.join(foreign_root, "1.json")
with open(foreign_file, "w") as fh:
    json.dump([remote_message(1, 1)], fh)
try:
    apply_plan({"evict": [{"path": foreign_file}]}, foreign_root)
    raise AssertionError("apply_plan accepted an unowned root")
except ScratchGuardError:
    pass
assert os.path.isfile(foreign_file)
# Marker present but the path is a different owned tree (foreign to this plan).
other = tempfile.mkdtemp(prefix="cache-retention-other-")
own_scratch(other)
other_file = os.path.join(other, "1.json")
with open(other_file, "w") as fh:
    json.dump([remote_message(1, 1)], fh)
try:
    apply_plan({"evict": [{"path": other_file}]}, guard_chats)
    raise AssertionError("apply_plan accepted a foreign owned path")
except ScratchGuardError:
    pass
assert os.path.isfile(other_file)
# DATA sentinel named in the plan: outside the owned chats root.
data_plan = {"evict": [{"path": guard["known_path"]}]}
try:
    apply_plan(data_plan, guard_chats)
    raise AssertionError("apply_plan accepted the DATA sentinel")
except ScratchGuardError:
    pass
assert os.path.isfile(guard["known_path"])
with open(guard["known_path"]) as fh:
    assert json.load(fh) == [10, 20]
ok("apply_plan rejects outside, symlink and foreign paths")

# own_scratch itself refuses a path outside the process temp dir and does
# not create it. HOME is under temp, so this uses a path that cannot be a
# profile and cannot sit under tempfile.gettempdir().
outside_own = os.path.join(os.sep, "haltia-must-not-own-scratch")
assert not os.path.exists(outside_own)
try:
    own_scratch(outside_own)
    raise AssertionError("own_scratch accepted a path outside the temp dir")
except ScratchGuardError:
    pass
assert not os.path.exists(outside_own)
ok("own_scratch stays in the process temp dir")

# --- present but unreadable/non-finite stamp: fail closed (skip), unlike
# a truly absent stamp. Exact kept/evicted/skipped/over_cap. ---------------
bad_root = tempfile.mkdtemp(prefix="cache-retention-badstamp-")
bad_chats = os.path.join(bad_root, "chats")
bad_cache = bm.MessageCache(bad_chats, delay=3600)
own_scratch(bad_chats)
bad_cache.folder = bad_chats
for cid in (1, 2, 3, 4, 5, 6):
    bad_cache.add(cid, [remote_message(1, cid, "c%d" % cid)])
bad_cache.flush()
p1, p2 = bad_cache._path(1), bad_cache._path(2)
mark_accessed(p1, 50)
os.utime(p1, (10, 10))
os.utime(p2, (200, 200))
write_stamp_raw(bad_cache._path(3), "not-a-number\n")
write_stamp_raw(bad_cache._path(4), "nan\n")
write_stamp_raw(bad_cache._path(5), "inf\n")
write_stamp_raw(bad_cache._path(6), "-inf\n")
assert read_access_stamp(p1) == 50
assert read_access_stamp(p2) is None
assert read_access_stamp(bad_cache._path(3)) is STAMP_INVALID
assert read_access_stamp(bad_cache._path(4)) is STAMP_INVALID
assert read_access_stamp(bad_cache._path(5)) is STAMP_INVALID
assert read_access_stamp(bad_cache._path(6)) is STAMP_INVALID
plan = plan_eviction(bad_chats, keep=1)
assert rels(bad_chats, plan["keep"]) == ["1.json"]
assert rels(bad_chats, plan["evict"]) == ["2.json"]
assert plan["keep"][0]["accessed"] == 50
assert plan["evict"][0]["accessed"] is None
assert plan["protected"] == []
skipped = set(plan["skipped"])
for cid in (3, 4, 5, 6):
    assert bad_cache._path(cid) in skipped
assert plan["skipped_count"] == 4
assert plan["files_before"] == 2
assert plan["files_after"] == 1
assert plan["over_cap"] is True
apply_plan(plan, bad_chats)
assert os.path.isfile(p1) and os.path.isfile(access_stamp_path(p1))
assert not os.path.exists(p2)
for cid in (3, 4, 5, 6):
    assert os.path.isfile(bad_cache._path(cid)), cid
    assert os.path.isfile(access_stamp_path(bad_cache._path(cid))), cid
ok("invalid access stamp fails closed")

# --- stamp lifecycle: production drop leaves an orphan; a recreated chat
# inherits it; fixture eviction of a stamped chat removes the stamp. This
# is design/test behaviour, not a production drop change. ------------------
life_root = tempfile.mkdtemp(prefix="cache-retention-lifecycle-")
life_chats = os.path.join(life_root, "chats")
life_cache = bm.MessageCache(life_chats, delay=3600)
own_scratch(life_chats)
life_cache.folder = life_chats
life_cache.add(1, [remote_message(1, 10, "keep")])
life_cache.add(2, [remote_message(1, 20, "drop-me")])
life_cache.flush()
life1, life2 = life_cache._path(1), life_cache._path(2)
mark_accessed(life1, 50)
mark_accessed(life2, 40)
stamp2 = access_stamp_path(life2)
assert os.path.isfile(stamp2)
life_cache.drop(2)
assert not os.path.isfile(life2)
assert os.path.isfile(stamp2)  # today's drop removes JSON only
plan = plan_eviction(life_chats, keep=1)
assert stamp2 in plan["orphan_stamps"]
assert plan["orphan_stamp_count"] == 1
assert rels(life_chats, plan["keep"]) == ["1.json"]
assert plan["evict"] == []
# Same id written again: the orphan stamp credits the new file.
life_cache.add(2, [remote_message(1, 30, "rejoined")])
life_cache.flush()
plan = plan_eviction(life_chats, keep=1)
assert plan["orphan_stamp_count"] == 0
assert rels(life_chats, plan["keep"]) == ["1.json"]
assert rels(life_chats, plan["evict"]) == ["2.json"]
assert plan["keep"][0]["accessed"] == 50
assert plan["evict"][0]["accessed"] == 40
apply_plan(plan, life_chats)
assert os.path.isfile(life1) and os.path.isfile(access_stamp_path(life1))
assert not os.path.exists(life2)
assert not os.path.exists(stamp2)
ok("stamp lifecycle drop orphan and evict removes stamp")
print("cache retention ok")
