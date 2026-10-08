"""Turning a build's gear, idols and affixes into save-file item data, plus the CSV export."""
import csv
import os
import random
from .common import APP_DIR, ENVIRONMENTS, EXTRA_AFFIX_FIELDS, SLOT_NAMES, SLOT_ORDER, _console, decode_affix_id, decode_item


# ----------------------------------------------------------------------------------------
# Item encoder (save-file "data" byte array) - based on the Epoch Item Decoder findings
# ----------------------------------------------------------------------------------------
# Equipped-slot container IDs (from the save file's containerID field).
CONTAINER_IDS = {"head": 2, "chest": 3, "weapon1": 4, "weapon2": 5, "hands": 6, "waist": 7,
                 "feet": 8, "ring1": 9, "ring2": 10, "amulet": 11, "relic": 12,
                 "idol_altar": 123}
IDOL_ALTAR_BASE_TYPE = 41  # Idol Altars: always corrupted (byte 8 = 16), forging potential 0
IDOL_ALTAR_FORGING_POTENTIAL = 0
# Idols: normal affix layout, no forging potential, equipped straight into the altar's idol
# grid (container 29). Last Epoch Tools gives each idol's TOP-left cell, 1-based, with y
# counting DOWN from the top row. The save file wants the BOTTOM-left cell, 0-based, with y
# counting UP from the bottom row (confirmed by seating a build's idols in game):
#     game_x = x - 1
#     game_y = IDOL_GRID_ROWS - (y + height - 1)
IDOL_GRID_CONTAINER = 29
IDOL_GRID_ROWS = 5
IDOL_FORGING_POTENTIAL = 0
IDOL_SIZES = {25: (1, 1), 26: (1, 1), 27: (2, 1), 28: (1, 2), 29: (3, 1), 30: (1, 3),
              31: (4, 1), 32: (1, 4), 33: (2, 2)}   # base type -> (width, height), from game data
ENCODE_ROLL = 255          # affix and implicit roll bytes (255 = perfect roll)
ENCODE_FORGING_POTENTIAL = 63  # byte 12 bits 0-5 (63 = max); type bits 6-7 = 0 (normal)
RARE_RARITY = 4            # byte 7 on rares; the game keeps 4 after a T8 upgrade
PRIMORDIAL_TIER = 8        # sealed primordial affixes are T8 records (tier nibble 7)
UNIQUE_RARITY = 7          # byte 7 on unique items
SET_RARITY = 8             # byte 7 on set items (unique layout, byte 22 = 0)
LEGENDARY_RARITY = 9       # byte 7 on uniques with legendary (slammed) affixes
UNIQUE_LEGENDARY_POTENTIAL = 0  # byte 22 on plain uniques (0-4)
CORRUPTED_FLAG = 16        # byte 8 bit 4
RECORD_FLAG_SEALED = 64    # record-count byte flag: first record is a sealed affix
RECORD_FLAG_CORRUPTION = 128  # record-count byte flag: last record is a corruption affix
UNIQUE_ROLL_SLOTS = 8      # unique items always carry 8 mod roll bytes [14-21]
SAVE_FORMAT_VERSION = 2    # the item object's "formatVersion" field


class EncodeError(Exception):
    pass


def encode_affix(affix_id, tier, roll=ENCODE_ROLL):
    """3-byte affix record: [tier/ID-high, ID-low, roll]."""
    if not (0 <= affix_id <= 0xFFF):
        raise EncodeError("affix ID %s does not fit in 12 bits" % affix_id)
    if not (1 <= tier <= 16):
        raise EncodeError("tier %s out of range" % tier)
    return [((tier - 1) << 4) | (affix_id >> 8), affix_id & 0xFF, roll]


def encode_item_data(base_type_id, subtype_id, affixes, sealed=None, rng=random,
                     corruption=None, corrupted=False, forging_potential=None, primordial=()):
    """affixes: list of (affix_id, tier) for the visible affixes, in order.
    sealed: (affix_id, tier) or None -> first record, flag 64 in byte 13.
    primordial: list of affix IDs for sealed primordial (T8) affixes. Each is an ordinary
      T8 record placed after the sealed affix and before the visible ones; it needs no flag
      in byte 13, and the item keeps rarity 4 (rare) in byte 7 (decoder: Rune of Evolution
      test on Champion Regalia).
    corruption: (affix_id, tier) or None -> last record, flag 128 in byte 13, byte 8 = 16.
    corrupted: set byte 8 = 16 without a corruption affix (e.g. Idol Altars).
    forging_potential: overrides ENCODE_FORGING_POTENTIAL (0-63).
    Returns the save file's data byte list."""
    if not (0 <= base_type_id <= 255 and 0 <= subtype_id <= 255):
        raise EncodeError("item type/subtype ID does not fit in one byte")
    if len(affixes) > 63:
        raise EncodeError("too many affixes")
    primordial = list(primordial)
    records = (([encode_affix(*sealed)] if sealed else [])
               + [encode_affix(aid, PRIMORDIAL_TIER) for aid in primordial]
               + [encode_affix(*a) for a in affixes])
    if corruption:
        records.append(encode_affix(*corruption))
    if len(records) > 63:
        raise EncodeError("too many affix records")
    data = [6]                                             # [0] format version
    data += [rng.randrange(256) for _ in range(4)]         # [1-4] per-item ID/seed (random)
    data += [base_type_id, subtype_id]                     # [5] base type, [6] subtype
    data += [RARE_RARITY if primordial else len(affixes)]  # [7] rarity / visible affix count
    fp = ENCODE_FORGING_POTENTIAL if forging_potential is None else forging_potential
    data += [CORRUPTED_FLAG if (corruption or corrupted) else 0]  # [8] flags (16 = corrupted)
    data += [ENCODE_ROLL] * 3                              # [9-11] implicit rolls
    data += [fp & 63]                # [12] forging potential, normal type
    data += [len(records) | (RECORD_FLAG_SEALED if sealed else 0)
             | (RECORD_FLAG_CORRUPTION if corruption else 0)]   # [13] record count + flags
    for r in records:                       # [14+] sealed, primordial, visible, corruption
        data += r
    return data


def item_object(data, container_id, position=(0, 0)):
    """The item object as it appears in a save file."""
    return {"itemData": None, "data": data,
            "inventoryPosition": {"x": position[0], "y": position[1]},
            "quantity": 1, "containerID": container_id, "formatVersion": SAVE_FORMAT_VERSION}


def encode_unique_data(base_type_id, subtype_id, unique_id, legendary_affixes=(), rng=random,
                       corruption_affix=None, primordial_affixes=(), is_set=False):
    """Unique / legendary item, per the decoder's findings.
    Plain unique (rarity 7), 23 bytes:
      [6, r,r,r,r, base, subtype, 7, 0, impl1-3, ID>>8, ID&255, 8 mod rolls, LP]
    Legendary (rarity 9): same through byte 21, then
      [22] = record count (+128 if the last record is a corruption affix),
      [23+] = one 3-byte affix record each, corruption affix last
    Corrupted legendary: byte 8 = 16 (confirmed from an in-game before/after).
    Primordial affixes (confirmed in game on Withstand the Elements): the item is stored as
    rarity 9 and each primordial affix is an ordinary record counted by byte 22.
    Record order: legendary affixes, primordial affixes, corruption affix (always last).
    Any extra affix (legendary, primordial or corruption) turns a plain unique into the
    rarity 9 layout.
    legendary_affixes / primordial_affixes: lists of (affix_id, tier);
    corruption_affix: (affix_id, tier) or None.
    Set items (is_set, confirmed on Isadora's Revenge and Sinathia's Resurrection): the plain
    unique layout with byte 7 = 8, the set item ID in [12-13] (same ID list as uniques) and
    byte 22 = 0, since sets can't take Legendary Potential."""
    if not (0 <= base_type_id <= 255 and 0 <= subtype_id <= 255):
        raise EncodeError("item type/subtype ID does not fit in one byte")
    if not (0 < unique_id <= 0xFFFF):
        raise EncodeError("unique ID %s does not fit in 16 bits" % unique_id)
    legendary_affixes = list(legendary_affixes)
    primordial_affixes = list(primordial_affixes)
    if len(legendary_affixes) > 4:
        raise EncodeError("more than 4 legendary affixes")
    extra = legendary_affixes + primordial_affixes + ([corruption_affix] if corruption_affix else [])
    if is_set and extra:
        raise EncodeError("set items with legendary, primordial or corruption affixes "
                          "are not encoded yet")
    if len(extra) > 63:
        raise EncodeError("too many affix records")
    data = [6]                                             # [0] format version
    data += [rng.randrange(256) for _ in range(4)]         # [1-4] random
    data += [base_type_id, subtype_id]                     # [5] base type, [6] base subtype
    data += [LEGENDARY_RARITY if extra else SET_RARITY if is_set else UNIQUE_RARITY]  # [7]
    data += [CORRUPTED_FLAG if corruption_affix else 0]    # [8] flags (16 = corrupted)
    data += [ENCODE_ROLL] * 3                              # [9-11] implicit rolls
    data += [unique_id >> 8, unique_id & 0xFF]             # [12-13] unique ID (16-bit)
    data += [ENCODE_ROLL] * UNIQUE_ROLL_SLOTS              # [14-21] unique mod rolls
    if extra:
        data += [len(extra) | (RECORD_FLAG_CORRUPTION if corruption_affix else 0)]  # [22]
        for aid, tier in extra:                            # [23+] affix records
            data += encode_affix(aid, tier)
    else:
        data += [UNIQUE_LEGENDARY_POTENTIAL]               # [22] legendary potential
    return data


def _affix_pair(a):
    aid = decode_affix_id(a.get("id", ""))
    if aid is None or a.get("tier") is None:
        raise EncodeError("could not read affix %r" % a.get("id"))
    return aid, int(a["tier"])


def _affix_list(value):
    """A primordialAffix field (one affix or a list, as Maxroll gives it) -> [(id, tier)]."""
    if not value:
        return []
    return [_affix_pair(a) for a in (value if isinstance(value, list) else [value])]


def idol_grid_position(x, y, height):
    """Last Epoch Tools idol x,y (1-based, top-left, y down) -> save-file position
    (0-based, bottom-left, y up)."""
    gx, gy = x - 1, IDOL_GRID_ROWS - (y + height - 1)
    if gx < 0 or gy < 0 or gy + height > IDOL_GRID_ROWS:
        raise EncodeError("idol position %s,%s does not fit the %d-row idol grid"
                          % (x, y, IDOL_GRID_ROWS))
    return gx, gy


def idol_size(item):
    info = decode_item(item.get("id", ""))
    return IDOL_SIZES.get(info.get("baseTypeId"), (1, 1))


def encode_build_item(slot_key, item, tables, rng=random):
    """Returns (data, container_id) for an equipped crafted or unique item, or an idol
    (slot_key "idol", container = Inventory), or raises EncodeError."""
    if slot_key == "idol":
        container = IDOL_GRID_CONTAINER
    elif slot_key not in CONTAINER_IDS:
        raise EncodeError("no known container for slot %s" % slot_key)
    else:
        container = CONTAINER_IDS[slot_key]
    info = decode_item(item.get("id", ""))
    uid = info.get("uniqueId") or 0
    if info.get("kind") == "U" or uid:
        u = tables["uniques"].get(str(uid))
        if not u:
            raise EncodeError("unique ID %s not found in the game data" % uid)
        bid = info.get("baseTypeId")
        if bid is None:
            bid = u.get("baseTypeId")
        sub = info.get("subTypeId")
        if bid is None or sub is None:
            raise EncodeError("could not work out the unique's base item")
        legendary = [_affix_pair(a) for a in item.get("affixes") or []]
        # LE Tools puts a unique's corruption affix in either corruptedAffix or sealedAffix.
        corr_fields = [f for f in ("corruptedAffix", "sealedAffix") if item.get(f)]
        if len(corr_fields) > 1:
            raise EncodeError("unique has both a corruptedAffix and a sealedAffix")
        corruption = _affix_pair(item[corr_fields[0]]) if corr_fields else None
        primordial = _affix_list(item.get("primordialAffix"))
        if corruption and corr_fields[0] == "sealedAffix" and corruption[1] >= PRIMORDIAL_TIER:
            primordial.append(corruption)   # a T8 "sealed" affix is primordial, not corruption
            corruption = None
        return (encode_unique_data(int(bid), int(sub), int(uid), legendary, rng, corruption,
                                   primordial, is_set=bool(u.get("isSet"))), container)
    if info.get("kind") != "I":
        raise EncodeError("unrecognised item code %r" % item.get("id"))
    if item.get("setAffix"):
        raise EncodeError("setAffix (a Reforged set affix on a crafted item) is not "
                          "supported by the encoder yet")

    affixes = [_affix_pair(a) for a in item.get("affixes") or []]
    sealed = _affix_pair(item["sealedAffix"]) if item.get("sealedAffix") else None
    corruption = _affix_pair(item["corruptedAffix"]) if item.get("corruptedAffix") else None
    # Sealed primordial (T8) affixes: LE Tools may list one as primordialAffix or as a
    # sealedAffix with tier 8. Either way it is written as a T8 record with no flag.
    primordial = [aid for aid, _tier in _affix_list(item.get("primordialAffix"))]
    if sealed and sealed[1] >= PRIMORDIAL_TIER:
        primordial.insert(0, sealed[0])
        sealed = None
    is_gear = (info["baseTypeId"] not in IDOL_SIZES
               and info["baseTypeId"] != IDOL_ALTAR_BASE_TYPE)
    if is_gear and corruption and not sealed:
        # Decoder (corrupted rare body armour): corrupting a crafted item adds a SEALED
        # affix as the first record (flag 64, not 128), sets byte 8 = 16 and drops
        # forging potential to 0.
        return (encode_item_data(info["baseTypeId"], info["subTypeId"], affixes, corruption,
                                 rng, corrupted=True, forging_potential=0,
                                 primordial=primordial), container)
    if info["baseTypeId"] in IDOL_SIZES:
        data = encode_item_data(info["baseTypeId"], info["subTypeId"], affixes, sealed, rng,
                                corruption, forging_potential=IDOL_FORGING_POTENTIAL,
                                primordial=primordial)
    elif info["baseTypeId"] == IDOL_ALTAR_BASE_TYPE:
        # Matches an equipped altar logged from the game: normal layout, corrupted, 0 FP.
        data = encode_item_data(info["baseTypeId"], info["subTypeId"], affixes, sealed, rng,
                                corruption, corrupted=True,
                                forging_potential=IDOL_ALTAR_FORGING_POTENTIAL,
                                primordial=primordial)
    else:
        data = encode_item_data(info["baseTypeId"], info["subTypeId"], affixes, sealed, rng,
                                corruption, primordial=primordial)
    return data, container


# ----------------------------------------------------------------------------------------
# Build -> rows
# ----------------------------------------------------------------------------------------
ITEM_ID_CSV = "last_epoch_item_subtypes_v1.5.0.csv"


class ItemIdLookup:
    """Looks up Item Type ID / Item Subtype ID by name from the item subtypes CSV
    (expected next to this script)."""

    def __init__(self, log=_console):
        self.type_ids, self.sub_ids, self.path = {}, {}, None
        path = os.path.join(APP_DIR, ITEM_ID_CSV)
        if not os.path.exists(path):  # accept a newer/other version of the same list
            import glob
            found = sorted(glob.glob(os.path.join(APP_DIR, "last_epoch_item_subtypes_*.csv")))
            path = found[-1] if found else None
        if not path:
            log("WARNING: %s not found next to the script - Item Type ID / Item Subtype ID "
                "columns will be blank." % ITEM_ID_CSV)
            return
        self.path = path
        with open(path, newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                t, s = r["Item Type"].strip(), r["Item Subtype"].strip()
                self.type_ids.setdefault(t.lower(), r["Item Type ID"].strip())
                self.sub_ids.setdefault((t.lower(), s.lower()), []).append(
                    (r["Item Subtype ID"].strip(), "obsolete" in r.get("Notes", "") or
                     "legacy" in r.get("Notes", "")))
        log("Item IDs from: %s" % os.path.basename(path))

    def type_id(self, type_name):
        return self.type_ids.get((type_name or "").lower(), "")

    def subtype_id(self, type_name, sub_name, decoded_id=None):
        hits = self.sub_ids.get(((type_name or "").lower(), (sub_name or "").lower()), [])
        if not hits:
            return ""
        if decoded_id is not None:  # same name used twice (e.g. legacy copy) -> prefer the real one
            for sid, _old in hits:
                if sid == str(decoded_id):
                    return sid
        current = [sid for sid, old in hits if not old]
        return (current or [hits[0][0]])[0]


def describe_item(code, tables):
    """Returns a dict: type (base type name), subtype (base subtype name), name, id, unique,
    plus the decoded base type / subtype numbers.
    Crafted: name/id are the subtype ('Ancestral Garb', 42).
    Unique:  name/id are the unique ("Mad Alchemist's Ladle", 321)."""
    info = decode_item(code)
    bid, sub = info.get("baseTypeId"), info.get("subTypeId")
    uid = info.get("uniqueId") or 0
    if info.get("kind") == "U" or uid:
        u = tables["uniques"].get(str(uid), {})
        if bid is None:  # 'U' codes don't carry the base type; get it from the unique
            bid = u.get("baseTypeId")
        base = tables["bases"].get(str(bid), "") or "Unknown"
        return {"type": base, "type_label": base + (" (Set)" if u.get("isSet") else ""),
                "subtype": tables["subtypes"].get("%s-%s" % (bid, sub), ""),
                "name": u.get("name") or "Unknown unique", "id": uid, "unique": True,
                "bid": bid, "sub": sub}
    base = tables["bases"].get(str(bid), "") if bid is not None else ""
    subtype = tables["subtypes"].get("%s-%s" % (bid, sub), "")
    return {"type": base, "type_label": base or "Unknown (%s)" % code, "subtype": subtype,
            "name": subtype, "id": sub if sub is not None else "", "unique": False,
            "bid": bid, "sub": sub}


def item_row(slot_label, item, tables, lookup, slot_key=None):
    affixes = list(item.get("affixes") or [])
    for field, _label in EXTRA_AFFIX_FIELDS:  # sealed / primordial / corrupted affixes go last
        value = item.get(field)
        if value:
            affixes.extend(value if isinstance(value, list) else [value])
    d = describe_item(item.get("id", ""), tables)
    ids, tiers, kinds, names = [], [], [], []
    for a in affixes:
        aid = decode_affix_id(a.get("id", ""))
        info = tables["affixes"].get(str(aid), {}) if aid is not None else {}
        ids.append(str(aid) if aid is not None else "?")
        tiers.append(str(a.get("tier", "?")))
        kinds.append({"Prefix": "P", "Suffix": "S"}.get(info.get("type"), "?"))
        names.append(info.get("name") or "?")
    return {
        "Item Slot": slot_label, "Item Type": d["type_label"],
        "Item Type ID": lookup.type_id(d["type"]),
        "Item Subtype ID": lookup.subtype_id(d["type"], d["subtype"], d["sub"]),
        "Name": d["name"], "ID": d["id"],
        "_unique": d["unique"], "Affix": ", ".join(ids), "Affix Tier": ", ".join(tiers),
        "Prefix/Suffix": ", ".join(kinds), "_names": names,
        **_encode_columns(slot_key, item, tables),
    }


def _encode_columns(slot_key, item, tables):
    if slot_key != "idol" and slot_key not in CONTAINER_IDS:
        return {"Data": "", "Container ID": "", "_object": None, "_encode_note": ""}
    try:
        data, container = encode_build_item(slot_key, item, tables)
        position = (0, 0)
        if slot_key == "idol":
            if item.get("x") is None or item.get("y") is None:
                raise EncodeError("the build gives no grid position for this idol")
            position = idol_grid_position(int(item["x"]), int(item["y"]), idol_size(item)[1])
    except EncodeError as e:
        return {"Data": "", "Container ID": "", "_object": None, "_encode_note": str(e)}
    return {"Data": "[" + ",".join(map(str, data)) + "]", "Container ID": container,
            "_object": item_object(data, container, position), "_encode_note": ""}


def build_rows(build, tables, lookup=None):
    lookup = lookup or ItemIdLookup()
    data = build.get("data", build)
    rows = []
    equipment = data.get("equipment") or {}
    for slot in SLOT_ORDER + [s for s in equipment if s not in SLOT_ORDER]:
        item = equipment.get(slot)
        if item and item.get("id"):
            rows.append(item_row(SLOT_NAMES.get(slot, slot), item, tables, lookup, slot))
    idols = [i for i in (data.get("idols") or []) if i.get("id")]
    for n, idol in enumerate(idols, 1):
        rows.append(item_row("Idol %d" % n, idol, tables, lookup, "idol"))
    return rows


_AFFIX_COLS = [("Affix", "Affix"), ("Affix Tier", "Affix Tier"), ("Prefix/Suffix", "Prefix/Suffix")]
# (table title, rows filter, [(column header, row key), ...])
TABLES = [
    ("Unique Items", True, [("Item Slot", "Item Slot"), ("Item Type", "Item Type"),
                            ("Item Type ID", "Item Type ID"), ("Item Subtype ID", "Item Subtype ID"),
                            ("Unique Name", "Name"), ("Unique ID", "ID")] + _AFFIX_COLS
                            + [("Container ID", "Container ID"), ("Data", "Data")]),
    ("Crafted Items", False, [("Item Slot", "Item Slot"), ("Item Type", "Item Type"),
                              ("Item Type ID", "Item Type ID"), ("Item Subtype", "Name"),
                              ("Item Subtype ID", "Item Subtype ID")] + _AFFIX_COLS
                             + [("Container ID", "Container ID"), ("Data", "Data")]),
]


def split_tables(rows):
    """Yields (title, headers, [[cell, ...], ...]) for each table."""
    for title, unique, cols in TABLES:
        body = [[r[key] for _h, key in cols] for r in rows if r["_unique"] == unique]
        yield title, [h for h, _k in cols], body


def format_summary(rows):
    out = []
    for title, headers, body in split_tables(rows):
        out += ["", "== %s ==" % title]
        if not body:
            out.append("(none)")
            continue
        widths = [max(len(h), *(len(str(row[i])) for row in body)) for i, h in enumerate(headers)]
        line = lambda cells: " | ".join(str(c).ljust(wd) for c, wd in zip(cells, widths)).rstrip()
        out += [line(headers), "-+-".join("-" * wd for wd in widths)] + [line(r) for r in body]
    ids = sorted({int(i) for r in rows for i in r["Affix"].split(", ") if i.isdigit()})
    out += ["", "All affix IDs in this build (%d): %s" % (len(ids), ", ".join(map(str, ids)))]
    return "\n".join(out).lstrip("\n")


# ----------------------------------------------------------------------------------------
# Build summary (class, level, skills) for the window
# ----------------------------------------------------------------------------------------
# Class index -> (class, [masteries 1-3]); mastery 0 means no mastery chosen.
CLASSES = [("Primalist", ["Beastmaster", "Shaman", "Druid"]),
           ("Mage", ["Sorcerer", "Spellblade", "Runemaster"]),
           ("Sentinel", ["Void Knight", "Forge Guard", "Paladin"]),
           ("Acolyte", ["Necromancer", "Lich", "Warlock"]),
           ("Rogue", ["Bladedancer", "Marksman", "Falconer"])]


def build_info(build, tables):
    """Returns {"class", "level", "specialized": [5], "hotbar": [5]} with "" where empty.
    Specialized skills are the build's skill trees in slot order; the hotbar is data.hud."""
    data = build.get("data", build)
    bio = data.get("bio") or {}
    skills = tables.get("skills") or {}

    def skill_name(tree_id):
        return skills.get(tree_id, tree_id) if tree_id else ""

    cls, mastery = bio.get("characterClass", build.get("class")), bio.get("chosenMastery", build.get("mastery"))
    class_text = ""
    if isinstance(cls, int) and 0 <= cls < len(CLASSES):
        name, masteries = CLASSES[cls]
        class_text = ("%s (%s)" % (masteries[mastery - 1], name)
                      if isinstance(mastery, int) and 1 <= mastery <= 3 else name)
    level = bio.get("level", build.get("level"))
    trees = sorted((t for t in data.get("skillTrees") or [] if t.get("treeID")),
                   key=lambda t: t.get("slotNumber", 0))
    specialized = [skill_name(t["treeID"]) for t in trees][:5]
    hotbar = [skill_name(h) for h in (data.get("hud") or [])][:5]
    return {"class": class_text, "level": "" if level is None else str(level),
            "specialized": specialized + [""] * (5 - len(specialized)),
            "hotbar": hotbar + [""] * (5 - len(hotbar))}


def export(code, build, tables, version, log, save_settings=None):
    """save_settings: {"character_name", "save_dir", "save_file_name", "hardcore",
    "solo_character_challenge", "environment"}, logged here; the
    save file itself is written by write_character_save."""
    if save_settings:
        log("Character name: %s" % (save_settings.get("character_name") or "(not set)"))
        log("Save folder:    %s" % (save_settings.get("save_dir") or "(not set)"))
        log("New save file:  %s" % (save_settings.get("save_file_name") or "(not set)"))
        mode = [m for m, on in (("Hardcore", save_settings.get("hardcore")),
                                ("Solo Character Found (SCF)",
                                 save_settings.get("solo_character_challenge"))) if on]
        log("Mode:           %s" % (", ".join(mode) or "Softcore"))
        env = save_settings.get("environment") or ENVIRONMENTS[0][0]
        log("Environment:    %s (cycle %s)" % (env, dict(ENVIRONMENTS).get(env, "?")))
    rows = build_rows(build, tables, ItemIdLookup(log))
    objects = [r["_object"] for r in rows if r.get("_object")]
    log("Game data: %s" % version)
    log("Encoded items: %d" % len(objects))
    for r in rows:
        if r.get("_encode_note"):
            log("  Not encoded - %s: %s" % (r["Item Slot"], r["_encode_note"]))
    return rows
