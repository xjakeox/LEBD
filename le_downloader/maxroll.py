"""Downloading builds from Maxroll planner links (https://maxroll.gg/last-epoch/planner/<id>).

A Maxroll planner holds one or more gear sets ("profiles", e.g. Starting / Endgame /
Aspirational Gear). The chosen set is converted into the same build layout Last Epoch Tools
uses, so the rest of the tool (CSV export, save writer, blessings) works unchanged. Game data
(names, skill trees, tree versions) still comes from Last Epoch Tools.

Maxroll's planner data (from planners.maxroll.gg/profiles/le/<id>, checked on i6ahli0t):
- items: {"<n>": {"itemType", "subType", "uniqueID"?, "affixes": [{"id", "tier", "roll"}],
  "corruptedAffixes"?, "implicits"?, "corrupted"?}} - the game's own IDs; rolls are 0-1.
- profile["items"]: slot name -> item number. profile["idols"]: 24 cells of the 5-wide idol
  grid, row by row from the top-left; each idol sits at its top-left cell.
- profile["blessings"]: 10 entries, timeline 1-10, {"itemType": 34, "subType", "implicits"}.
- passives / skillTrees[treeID] / weaver: {"history": [node clicked, ...], "position": n};
  the first n clicks are the allocated points.
- specializedSkills / activeSkills: skill names without spaces ("AssembleAbomination").
"""
import json
import re

from .common import SITE, logger
from .let_fetch import WebSource, fill_tree_versions, load_tables

PROFILE_API = "https://planners.maxroll.gg/profiles/le/%s"
_PLANNER_RX = re.compile(r"maxroll\.gg/last-epoch/planner/([A-Za-z0-9]+)(?:[^#\s]*)(?:#(\d+))?", re.I)

# Maxroll slot name -> Last Epoch Tools slot name.
SLOT_MAP = {"head": "head", "body": "chest", "hands": "hands", "waist": "waist", "feet": "feet",
            "neck": "amulet", "finger1": "ring1", "finger2": "ring2", "relic": "relic",
            "weapon": "weapon1", "offhand": "weapon2", "offHand": "weapon2", "weapon2": "weapon2",
            "altar": "idol_altar"}
IDOL_GRID_WIDTH = 5
UNIQUE_RARITY_DIGIT = 7


def is_maxroll_link(text):
    return "maxroll.gg" in (text or "").lower()


def parse_maxroll_link(text):
    """'https://maxroll.gg/last-epoch/planner/i6ahli0t#2' -> ('i6ahli0t', 2)."""
    m = _PLANNER_RX.search(text or "")
    if not m:
        raise ValueError("That isn't a Maxroll planner link. Paste the build's planner link "
                         "(maxroll.gg/last-epoch/planner/...), not the guide page.")
    return m.group(1), int(m.group(2)) if m.group(2) else None


# ----------------------------------------------------------------------------------------
# lz-string compressToEncodedURIComponent (Last Epoch Tools' ID format, see common.py)
# ----------------------------------------------------------------------------------------
_LZ_KEY = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+-$"


def lz_compress_uri(text):
    out, val, pos = [], 0, 0

    def write(value, nbits):
        nonlocal val, pos
        for _ in range(nbits):
            val = (val << 1) | (value & 1)
            value >>= 1
            pos += 1
            if pos == 6:
                out.append(_LZ_KEY[val])
                val, pos = 0, 0

    dictionary, to_create = {}, set()
    w, enlarge_in, dict_size, num_bits = "", 2, 3, 2

    def emit_w():
        nonlocal enlarge_in, num_bits
        if w in to_create:
            code = ord(w[0])
            if code < 256:
                write(0, num_bits)
                write(code, 8)
            else:
                write(1, num_bits)
                write(code, 16)
            enlarge_in -= 1
            if enlarge_in == 0:
                enlarge_in, num_bits = 2 ** num_bits, num_bits + 1
            to_create.discard(w)
        else:
            write(dictionary[w], num_bits)
        enlarge_in -= 1
        if enlarge_in == 0:
            enlarge_in, num_bits = 2 ** num_bits, num_bits + 1

    for c in text:
        if c not in dictionary:
            dictionary[c] = dict_size
            dict_size += 1
            to_create.add(c)
        wc = w + c
        if wc in dictionary:
            w = wc
        else:
            emit_w()
            dictionary[wc] = dict_size
            dict_size += 1
            w = c
    if w:
        emit_w()
    write(2, num_bits)
    while True:   # flush the last character
        val <<= 1
        pos += 1
        if pos == 6:
            out.append(_LZ_KEY[val])
            break
    return "".join(out)


def item_code(item_type, sub_type, unique_id=None):
    """Last Epoch Tools item code: 'I' + lz("1" + base(3) + subtype(3) + rarity(1) + uniqueId)."""
    if unique_id is None:
        digits = "1%03d%03d000" % (item_type, sub_type)
    else:
        digits = "1%03d%03d%d%d" % (item_type, sub_type, UNIQUE_RARITY_DIGIT, unique_id)
    return "I" + lz_compress_uri(digits)


def affix_code(a):
    return {"id": "A" + lz_compress_uri(str(int(a["id"]))), "tier": int(a.get("tier") or 1)}


def roll_byte(r):
    """Maxroll roll (0-1) -> save-file roll byte (0-255)."""
    try:
        return max(0, min(255, int(round(float(r) * 255))))
    except (TypeError, ValueError):
        return 255


# ----------------------------------------------------------------------------------------
# Maxroll set -> Last Epoch Tools build layout
# ----------------------------------------------------------------------------------------
def _points(tree):
    """{"history": [...], "position": n} -> {"node": points} for the first n clicks."""
    tree = tree or {}
    history = tree.get("history") or []
    pos = tree.get("position", len(history))
    counts = {}
    for node in history[:pos]:
        counts[str(node)] = counts.get(str(node), 0) + 1
    return counts


def _norm(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def convert_item(item, log, label):
    """Maxroll item -> Last Epoch Tools item dict (id code + affix codes)."""
    uid = item.get("uniqueID")
    out = {"id": item_code(int(item["itemType"]), int(item["subType"]),
                           int(uid) if uid is not None else None),
           "affixes": [affix_code(a) for a in item.get("affixes") or []]}
    corrupted = item.get("corruptedAffixes") or []
    if corrupted:
        out["corruptedAffix"] = affix_code(corrupted[0])
        if len(corrupted) > 1:
            log("  %s: has %d corruption affixes; only the first is written" % (label, len(corrupted)))
    sealed = item.get("sealedAffix") or (item.get("sealedAffixes") or [None])[0]
    if sealed:
        out["sealedAffix"] = affix_code(sealed)
    for field in ("primordialAffix", "primordialAffixes"):
        if item.get(field):
            vals = item[field] if isinstance(item[field], list) else [item[field]]
            out["primordialAffix"] = [affix_code(a) for a in vals]
    return out


def profile_to_build(profile, items, tables, log):
    """One Maxroll gear set -> {"data": {...}} in the Last Epoch Tools planner layout."""
    def get_item(n):
        return items.get(str(n)) if n is not None else None

    equipment = {}
    for slot, n in (profile.get("items") or {}).items():
        item = get_item(n)
        if not item:
            continue
        key = SLOT_MAP.get(slot)
        if not key:
            log("  Slot %r is not supported yet; skipped" % slot)
            continue
        equipment[key] = convert_item(item, log, slot)

    idols = []
    for cell, n in enumerate(profile.get("idols") or []):
        item = get_item(n)
        if item:
            idol = convert_item(item, log, "idol")
            idol["x"], idol["y"] = cell % IDOL_GRID_WIDTH + 1, cell // IDOL_GRID_WIDTH + 1
            idols.append(idol)

    blessings = {}
    for timeline, b in enumerate(profile.get("blessings") or [], 1):
        if b and b.get("subType") is not None:
            rolls = [roll_byte(r) for r in (b.get("implicits") or [])][:3]
            blessings[str(timeline)] = {"id": item_code(int(b.get("itemType", 34)), int(b["subType"])),
                                        "ir": rolls + [255] * (3 - len(rolls))}

    # Skill names ("AssembleAbomination") -> tree IDs, via Last Epoch Tools' skill names.
    by_name = {_norm(name): tid for tid, name in (tables.get("skills") or {}).items()}
    trees = profile.get("skillTrees") or {}
    order = []
    for name in profile.get("specializedSkills") or []:
        tid = by_name.get(_norm(name))
        if tid in trees and tid not in order:
            order.append(tid)
        elif name:
            log("  Specialized skill %r has no matching skill tree in the planner" % name)
    order += [t for t in trees if t not in order]   # anything left, in the planner's order
    skill_trees = [{"treeID": tid, "selected": _points(trees[tid]), "slotNumber": i}
                   for i, tid in enumerate(order[:5])]
    hud = []
    for name in profile.get("activeSkills") or []:
        tid = by_name.get(_norm(name))
        if not tid and name:
            log("  Hotbar skill %r not found in the game data; left empty" % name)
        hud.append(tid or "")

    data = {"bio": {"level": profile.get("level", 100), "characterClass": profile.get("class"),
                    "chosenMastery": profile.get("mastery", 0)},
            "equipment": equipment, "idols": idols, "blessings": blessings,
            "charTree": {"treeID": "", "selected": _points(profile.get("passives"))},
            "skillTrees": skill_trees,
            "weaverTree": {"selected": _points(profile.get("weaver"))},
            "hud": hud}
    if profile.get("weaverItems"):
        log("  Weaver items are not written yet; skipped")
    return {"data": data, "source": "maxroll", "set": profile.get("name")}


def choose_profile(profiles, wanted, active, choose_set):
    """Index of the gear set to use. One set: no question. Otherwise choose_set(names,
    default_index) asks the user (None = cancelled); without it the link's #n or the
    planner's active set is used."""
    if len(profiles) == 1:
        return 0
    default = active if isinstance(active, int) and 0 <= active < len(profiles) else 0
    if wanted is not None and 1 <= wanted <= len(profiles):   # "#2" in the link = 2nd set
        default = wanted - 1
    if choose_set is None:
        return default
    names = [p.get("name") or "Set %d" % (i + 1) for i, p in enumerate(profiles)]
    choice = choose_set(names, default)
    if choice is None:
        raise ValueError("No gear set was chosen, so nothing was downloaded.")
    return choice


def run_from_link(link, log, choose_set=None):
    """Same result as let_fetch.run_from_link: (code, build, tables, version)."""
    planner_id, wanted = parse_maxroll_link(link)
    src = WebSource(log)
    url = PROFILE_API % planner_id
    log("Fetching Maxroll planner %s..." % planner_id)
    raw = src.get(url, "https://maxroll.gg/")
    try:
        outer = json.loads(raw)
        planner = json.loads(outer["data"]) if isinstance(outer.get("data"), str) else outer["data"]
        profiles = planner["profiles"]
        items = planner.get("items") or {}
    except (ValueError, KeyError, TypeError):
        logger.exception("Unexpected Maxroll data")
        raise ValueError("Maxroll sent something that isn't planner data. Check the link opens "
                         "in a browser.")
    if not profiles:
        raise ValueError("That Maxroll planner has no gear sets.")
    index = choose_profile(profiles, wanted, planner.get("activeProfile"), choose_set)
    profile = profiles[index]
    log("Build: %s - %s" % (outer.get("name") or planner_id, profile.get("name") or "set %d" % (index + 1)))

    page = src.get("/planner/", SITE + "/")   # Last Epoch Tools game data
    tables, version = load_tables(src, page, log)
    build = profile_to_build(profile, items, tables, log)
    fill_tree_versions(build, src, page, version, log)
    set_tag = re.sub(r"[^A-Za-z0-9]+", "_", profile.get("name") or str(index + 1)).strip("_")
    return "maxroll_%s_%s" % (planner_id, set_tag), build, tables, version
