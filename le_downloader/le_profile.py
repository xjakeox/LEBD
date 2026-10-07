"""Last Epoch Tools profile character links:
    https://www.lastepochtools.com/profile/<player>/character/<name>
    https://www.lastepochtools.com/profile/<player>/character/<name>/snapshot/<snapshot>

A profile page has a dropdown (top right) of the character's snapshots. Picking one adds
/snapshot/<value> to the link. The values and labels, as the site's profile script builds them:
  latest                  "Latest" (the plain link)
  ladder-season-end       "Season End"
  ladder-week-N           "Week N"   (newest first)
  ladder-day-N            "Day N"    (newest first)
  aberroth, uber_aberroth, vision_of_the_observer, morditas, uber_morditas   (kill tracking)
  hardcore_death          (hardcore characters)
The list comes from the page's profile_data answer, not the page itself:
  ladderSnapshots.slots[].slot          -> ladder snapshots that exist ("day-5", "week-1", ...)
  charInfo.extras (a JSON string)       -> <boss>KillTracking.snapshot set when a kill snapshot exists;
                                           hardcoreDeathTracking[2] for the death snapshot
The site shows the others greyed out; only the ones that exist are offered here.

With a picker (the GUI's scrollable list) the user chooses; without one (command line) the
snapshot in the pasted link is used. The build itself is read like a planner page
(let_fetch.load_page_data / finish_build).
"""
import json
import re
from .common import logger
from .let_fetch import WebSource, finish_build, load_page_data

_PROFILE = re.compile(r"profile/([^/?#\s]+)/character/([^/?#\s]+)(?:/snapshot/([^/?#\s]+))?")

LADDER = "ladder-"
KILLS = [("aberroth", "aberrothKillTracking", "Aberroth killed"),
         ("uber_aberroth", "uberAberrothKillTracking", "Uber Aberroth killed"),
         ("vision_of_the_observer", "visionOfTheObserverKillTracking", "Vision of the Observer killed"),
         ("morditas", "morditasTracking", "Morditas killed"),
         ("uber_morditas", "uberMorditasTracking", "Uber Morditas killed")]
HARDCORE_DEATH = "hardcore_death"


def is_profile_link(text):
    return bool(_PROFILE.search(text or "")) and "maxroll.gg" not in text


def parse_profile_link(text):
    """-> (base path, code for file names, snapshot value or "latest")."""
    m = _PROFILE.search(text.strip())
    if not m:
        raise ValueError("That doesn't look like a Last Epoch Tools profile character link.")
    user, char, snap = m.group(1), m.group(2), m.group(3) or "latest"
    code = re.sub(r"[^A-Za-z0-9_-]", "_", "%s_%s" % (user, char))
    return "/profile/%s/character/%s" % (user, char), code, snap


def snapshot_path(base, value):
    return base if value == "latest" else "%s/snapshot/%s" % (base, value)


def _ladder_label(slot):
    if slot == "season-end":
        return "Season End"
    kind, _, num = slot.partition("-")
    return "%s %s" % ("Day" if kind == "day" else "Week", num)


def _ladder_order(slot):
    """Season end first, then weeks, then days, each newest first (as the site lists them)."""
    kind, _, num = slot.partition("-")
    rank = {"season": 0, "week": 1, "day": 2}.get(kind, 3)
    return rank, -int(num) if num.isdigit() else 0


def find_snapshots(data):
    """The dropdown's selectable entries as [(label, value)], newest first."""
    out = [("Latest", "latest")]
    char = data.get("charInfo") or {}
    snap_info = data.get("snapshotInfo") or {}
    if isinstance(snap_info, dict) and snap_info.get("characterGone"):
        out = []   # the site greys out Latest when the character was deleted
    ladder = data.get("ladderSnapshots") or {}
    slots = [s.get("slot") for s in (ladder.get("slots") or []) if isinstance(s, dict) and s.get("slot")]
    for slot in sorted(dict.fromkeys(slots), key=_ladder_order):
        out.append((_ladder_label(slot), LADDER + slot))
    extras = char.get("extras")
    if isinstance(extras, str):
        try:
            extras = json.loads(extras)
        except ValueError:
            extras = None
    if isinstance(extras, dict):
        for value, key, label in KILLS:
            if isinstance(extras.get(key), dict) and extras[key].get("snapshot"):
                out.append((label, value))
        death = extras.get("hardcoreDeathTracking")
        if char.get("hardcore") and isinstance(death, list) and len(death) > 2 and death[2]:
            out.append(("Hardcore death", HARDCORE_DEATH))
    return out


def choose_snapshot(snaps, wanted, choose):
    """Index of the snapshot to download. choose(labels, default_index) asks the user
    (None = cancelled); without it the snapshot in the link is used."""
    default = next((i for i, (_, v) in enumerate(snaps) if v == wanted), 0)
    if choose is None or len(snaps) <= 1:
        return default
    choice = choose([label for label, _ in snaps], default)
    if choice is None:
        raise ValueError("No day or event was chosen, so nothing was downloaded.")
    return choice


def run_from_link(link, log, choose=None):
    """Same result as let_fetch.run_from_link: (code, build, tables, version)."""
    base, code, wanted = parse_profile_link(link)
    src = WebSource(log)
    path = snapshot_path(base, wanted)
    page, data, build = load_page_data(src, path, code, log)
    snaps = find_snapshots(data if isinstance(data, dict) else {})
    logger.info("Profile data keys: %s; ladderSnapshots: %s", list(data) if isinstance(data, dict) else type(data),
                json.dumps(data.get("ladderSnapshots"))[:500] if isinstance(data, dict) else "")
    logger.info("Profile snapshots: %s", [v for _, v in snaps])
    if wanted not in [v for _, v in snaps]:
        snaps.insert(0, ("This link's snapshot (%s)" % wanted, wanted))
    if choose is None and wanted == "latest" and len(snaps) > 1:
        log("  (command line: downloading Latest; paste a /snapshot/ link for another day or event)")
    index = choose_snapshot(snaps, wanted, choose)
    label, value = snaps[index]
    log("Snapshot: %s" % label)
    if value != wanted:
        path = snapshot_path(base, value)
        page, _, build = load_page_data(src, path, code, log)
    return finish_build(src, path, code, page, build, log)
