"""Building a character save from the class template and writing it to the Saves folder."""
import json
import os
import re
from .common import APP_DIR, _console
from .items import CLASSES, CONTAINER_IDS, IDOL_GRID_CONTAINER
from .blessings import BLESSING_BASE_TYPE, apply_blessings, unlock_empowered


# ----------------------------------------------------------------------------------------
# Offline save folder and save file naming
# ----------------------------------------------------------------------------------------
SAVE_FILE_PREFIX = "1CHARACTERSLOT_BETA_"
_SAVE_SLOT_RX = re.compile(r"^%s(\d+)(?!\d)" % re.escape(SAVE_FILE_PREFIX), re.I)


def find_default_save_dir():
    """Returns the usual offline Saves folder if it exists, else ""."""
    homes = [os.environ.get("USERPROFILE"), os.path.expanduser("~")]
    for home in filter(None, homes):
        path = os.path.join(home, "AppData", "LocalLow", "Eleventh Hour Games", "Last Epoch", "Saves")
        if os.path.isdir(path):
            return path
    return ""


def save_slot_numbers(save_dir):
    """Slot numbers N of the 1CHARACTERSLOT_BETA_N files in save_dir (backups count too)."""
    try:
        names = os.listdir(save_dir)
    except OSError:
        return []
    return sorted({int(m.group(1)) for m in map(_SAVE_SLOT_RX.match, names) if m})


def next_save_file_name(save_dir):
    """One past the highest existing slot, e.g. slots 0-2 present -> 1CHARACTERSLOT_BETA_3.
    An empty or missing folder gives slot 0."""
    slots = save_slot_numbers(save_dir) if save_dir else []
    return SAVE_FILE_PREFIX + str(slots[-1] + 1 if slots else 0)


# ----------------------------------------------------------------------------------------
# Character save writer
# ----------------------------------------------------------------------------------------
TEMPLATE_DIR = os.path.join(APP_DIR, "OriginalCharacterFiles")
SAVE_HEADER = "EPOCH"
SKILL_XP = 5700000          # skill xp in a level-20 skill tree, copied from a real save
EQUIPPED_CONTAINERS = set(CONTAINER_IDS.values()) | {IDOL_GRID_CONTAINER}

class SaveError(Exception):
    pass


def _tree_nodes(selected):
    """LE Tools {"nodeID": points} -> (nodeIDs, nodePoints), skipping 0-point roots."""
    pairs = [(int(k), int(v)) for k, v in (selected or {}).items() if int(v) > 0]
    return [k for k, _ in pairs], [v for _, v in pairs]


def load_template(class_index):
    """Reads (never writes) OriginalCharacterFiles/<Class>; returns the save dict."""
    if not (isinstance(class_index, int) and 0 <= class_index < len(CLASSES)):
        raise SaveError("the build's class (%r) is not recognised" % class_index)
    path = os.path.join(TEMPLATE_DIR, CLASSES[class_index][0])
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            text = f.read()
    except OSError:
        raise SaveError("template not found: %s" % path)
    if not text.startswith(SAVE_HEADER):
        raise SaveError("%s does not look like a Last Epoch save" % path)
    return json.loads(text[len(SAVE_HEADER):])


def build_character_save(build, rows, character_name, slot_number):
    """Copies the class template and fills in the build. Returns the save dict."""
    data = build.get("data", build)
    bio = data.get("bio") or {}
    save = load_template(bio.get("characterClass", build.get("class")))
    mastery = bio.get("chosenMastery", build.get("mastery")) or 0
    save["characterName"] = character_name
    save["level"] = int(bio.get("level", build.get("level")) or save.get("level", 100))
    save["chosenMastery"] = save["originalMastery"] = int(mastery)
    if slot_number is not None:
        save["id"] = str(slot_number)

    # Items: keep the template's items, but the build's gear replaces starter gear in the
    # same equipped slot (two items can't share one slot).
    new_items = [r["_object"] for r in rows if r.get("_object")]
    taken = {o["containerID"] for o in new_items if o["containerID"] != IDOL_GRID_CONTAINER}
    kept = [o for o in save.get("savedItems") or [] if o.get("containerID") not in taken]
    save["savedItems"] = kept + new_items

    tree = data.get("charTree") or {}
    ids, pts = _tree_nodes(tree.get("selected"))
    save["savedCharacterTree"] = {"treeID": tree.get("treeID") or "", "version": tree.get("version", 0),
                                  "nodeIDs": ids, "nodePoints": pts, "unspentPoints": 0,
                                  "nodesTaken": None}
    skill_trees = []
    for t in sorted((t for t in data.get("skillTrees") or [] if t.get("treeID")),
                    key=lambda t: t.get("slotNumber", 0)):
        ids, pts = _tree_nodes(t.get("selected"))
        skill_trees.append({"treeID": t["treeID"], "slotNumber": t.get("slotNumber", 0),
                            "xp": SKILL_XP, "version": t.get("version", 0), "nodeIDs": ids,
                            "nodePoints": pts, "unspentPoints": 0, "nodesTaken": None,
                            "abilityXP": 0.0})
    save["savedSkillTrees"] = skill_trees
    weaver = data.get("weaverTree") or {}
    ids, pts = _tree_nodes(weaver.get("selected"))
    save["savedWeaverTree"] = {"version": weaver.get("version", 0), "nodeIDs": ids, "nodePoints": pts}
    hud = [h for h in data.get("hud") or [] if h]
    if hud:
        bar = list(save.get("abilityBar") or [])
        bar[:len(hud)] = hud[:5]
        save["abilityBar"] = bar
    apply_blessings(save, build)
    unlock_empowered(save)
    return save


def write_character_save(build, rows, settings, log=_console):
    """Writes the new save into the Saves folder. Never overwrites an existing file and never
    modifies the templates. Returns the written path."""
    name = (settings.get("character_name") or "").strip()
    save_dir = (settings.get("save_dir") or "").strip()
    file_name = (settings.get("save_file_name") or "").strip()
    if not name:
        raise SaveError("enter a character name")
    if not save_dir or not os.path.isdir(save_dir):
        raise SaveError("the Saves folder does not exist: %s" % (save_dir or "(not set)"))
    if not file_name or os.path.basename(file_name) != file_name:
        raise SaveError("the new save file name is not valid: %r" % file_name)
    path = os.path.join(save_dir, file_name)
    if os.path.exists(path):
        raise SaveError("%s already exists; it was not overwritten" % file_name)
    m = _SAVE_SLOT_RX.match(file_name)
    save = build_character_save(build, rows, name, int(m.group(1)) if m else None)
    with open(path, "x", encoding="utf-8") as f:   # "x": fail rather than overwrite
        f.write(SAVE_HEADER + json.dumps(save, separators=(",", ":")))
    log("Saved character: %s" % path)
    n = sum(1 for o in save["savedItems"] if o.get("data", [0] * 6)[5:6] == [BLESSING_BASE_TYPE])
    if n:
        log("Blessings written: %d" % n)
    return path


_SAVE_FILE_RX = re.compile(r"^%s(\d+)$" % re.escape(SAVE_FILE_PREFIX), re.I)


def list_character_saves(save_dir):
    """Character saves (exactly 1CHARACTERSLOT_BETA_N, no backups) in slot order:
    [{"file", "path", "slot", "name", "level", "class"}]. Unreadable files are still listed."""
    try:
        names = os.listdir(save_dir)
    except OSError:
        return []
    saves = []
    for fn in names:
        m = _SAVE_FILE_RX.match(fn)
        path = os.path.join(save_dir, fn)
        if not m or not os.path.isfile(path):
            continue
        entry = {"file": fn, "path": path, "slot": int(m.group(1)),
                 "name": "(unreadable)", "level": "", "class": ""}
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                text = f.read()
            d = json.loads(text[len(SAVE_HEADER):] if text.startswith(SAVE_HEADER) else text)
            entry["name"] = d.get("characterName") or ""
            entry["level"] = str(d.get("level", ""))
            cls, mastery = d.get("characterClass"), d.get("chosenMastery")
            if isinstance(cls, int) and 0 <= cls < len(CLASSES):
                cname, masteries = CLASSES[cls]
                entry["class"] = ("%s (%s)" % (masteries[mastery - 1], cname)
                                  if isinstance(mastery, int) and 1 <= mastery <= 3 else cname)
        except (OSError, ValueError, AttributeError):
            pass
        saves.append(entry)
    return sorted(saves, key=lambda e: e["slot"])
