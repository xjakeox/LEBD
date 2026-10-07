"""Blessings, Monolith timelines and the Empowered Monolith unlock."""
import random
from .common import decode_item
from .items import ENCODE_ROLL, encode_item_data, item_object


# Blessings (from Jake's save with one blessing equipped and three unlocked):
# - An equipped blessing is an ordinary item: base type 34, rarity 0, no affixes, forging
#   potential 0, bytes 9-11 = its three implicit rolls. Containers: timeline 1 (Fall of
#   the Outcasts) = 33 and 2-7 = 34-39 (blessings applied in game); timeline 8 (The Last
#   Ruin) = 43 (Jake's save), so 9 and 10 are taken as 44 and 45. 40-42 do not work.
# - Unlocked blessings are listed in the save's "openBlessings" as
#   {subtypeId, implicitRollByte0-2}, including the equipped one with the same rolls.
# - "blessingsDiscovered" is filled with the subtype IDs too. The game still labels them
#   "undiscovered", but their effects work (checked on the stat sheet).
# LE Tools stores them as data.blessings {"<timeline 1-10>": {"id": "I...", "ir": [r, r, r]}}.
BLESSING_BASE_TYPE = 34
BLESSING_CONTAINERS = {1: 33, 2: 34, 3: 35, 4: 36, 5: 37, 6: 38, 7: 39, 8: 43, 9: 44, 10: 45}


def build_blessings(build, rng=random):
    """LE Tools blessings -> [(timeline, subtype, rolls, item object)], in timeline order."""
    data = build.get("data", build)
    out = []
    for key, b in sorted((data.get("blessings") or {}).items(), key=lambda kv: int(kv[0])):
        info = decode_item((b or {}).get("id") or "")
        if info.get("baseTypeId") != BLESSING_BASE_TYPE or int(key) not in BLESSING_CONTAINERS:
            continue
        rolls = [int(r) & 255 for r in (b.get("ir") or [])][:3]
        rolls += [ENCODE_ROLL] * (3 - len(rolls))
        item = encode_item_data(BLESSING_BASE_TYPE, info["subTypeId"], [], rng=rng,
                                forging_potential=0)
        item[9:12] = rolls
        out.append((int(key), info["subTypeId"], rolls,
                    item_object(item, BLESSING_CONTAINERS[int(key)])))
    return out


def apply_blessings(save, build):
    """Equips the build's blessings, marks them unlocked and discovered, and marks all 10
    timelines completed so the game keeps them. Changes save in place."""
    blessings = build_blessings(build)
    if not blessings:
        return
    slots = {o["containerID"] for _, _, _, o in blessings}
    save["savedItems"] = ([o for o in save["savedItems"] if o.get("containerID") not in slots]
                          + [o for _, _, _, o in blessings])
    opened = [b for b in save.get("openBlessings") or []
              if b.get("subtypeId") not in {sub for _, sub, _, _ in blessings}]
    save["openBlessings"] = opened + [
        {"subtypeId": sub, "implicitRollByte0": r[0], "implicitRollByte1": r[1],
         "implicitRollByte2": r[2]} for _, sub, r, _ in blessings]
    # Blessings on timelines the character hasn't unlocked are dropped by the game (Jake:
    # The Last Ruin, The Age of Winter and Spirits of Fire). Mark all 10 timelines as
    # completed on normal difficulty, the way Jake's save recorded Fall of the Outcasts:
    # {"timelineID": 1, "progress": [0]}. Timeline IDs match LE Tools' 1-10 (The Last Ruin = 8 in Jake's save).
    for key in ("timelineCompletion", "timelineDifficultyCompletion"):
        done = {t.get("timelineID"): t for t in save.get(key) or []}
        for tl in range(1, 11):
            entry = done.setdefault(tl, {"timelineID": tl, "progress": []})
            if 0 not in entry["progress"]:
                entry["progress"].append(0)
        save[key] = [done[k] for k in sorted(done)]
    save["monolithTimelinesConquered"] = max(save.get("monolithTimelinesConquered") or 0, 10)
    # Assumed to be a list of subtype IDs (Jake's samples had it empty). It doesn't clear the
    # "undiscovered" label, but it's harmless.
    found = [x for x in save.get("blessingsDiscovered") or []]
    save["blessingsDiscovered"] = found + [sub for _, sub, _, _ in blessings
                                           if sub not in found]


def unlock_empowered(save):
    """Makes the Empowered Monolith available on every timeline. Changes save in place."""
    # Empowered Monolith: Jake's save after unlocking it lists every timeline in
    # timelineDifficultyUnlocks with progress [0, 1] (0 = normal, 1 = empowered).
    unlocks = {t.get("timelineID"): t for t in save.get("timelineDifficultyUnlocks") or []}
    for tl in range(1, 11):
        entry = unlocks.setdefault(tl, {"timelineID": tl, "progress": []})
        for diff in (0, 1):
            if diff not in entry["progress"]:
                entry["progress"].append(diff)
    save["timelineDifficultyUnlocks"] = [unlocks[k] for k in sorted(unlocks)]
