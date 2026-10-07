"""Reading planner links from Last Epoch Tools, plus the parts profile and Maxroll links
share: page fetching, game data tables and skill tree versions."""
import json
import os
import re
import shutil
import subprocess
import urllib.request
import urllib.error
from .common import CACHE_DIR, SITE, UA, logger


# ----------------------------------------------------------------------------------------
# Minimal JavaScript object-literal -> Python converter (the item DB is a JS file)
# ----------------------------------------------------------------------------------------
_TOKEN = re.compile(r'''
    (?P<ws>\s+)
  | (?P<str>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
  | (?P<num>-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)
  | (?P<bang>![01])
  | (?P<ident>[A-Za-z_$][A-Za-z0-9_$]*)
  | (?P<punct>[{}\[\]:,])
''', re.S | re.X)


_SPLIT = re.compile(r'''\s*\.split\(\s*("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')\s*\)''')


def _js_string_to_json(s):
    if s[0] == '"':
        return s
    inner = s[1:-1].replace("\\'", "'").replace('"', '\\"')
    return '"' + inner + '"'


def js_literal_to_python(text, start):
    """Parse the JS object literal beginning at text[start] ('{'); returns the Python object."""
    out = []
    depth = 0
    pos = start
    n = len(text)
    prev_sig = None  # previous significant token text
    while pos < n:
        m = _TOKEN.match(text, pos)
        if not m:
            raise ValueError("Unexpected character %r at %d" % (text[pos], pos))
        pos = m.end()
        kind = m.lastgroup
        tok = m.group(kind)
        if kind == "ws":
            continue
        if kind == "punct":
            if tok in "{[":
                depth += 1
            elif tok in "}]":
                depth -= 1
            out.append(tok)
            prev_sig = tok
            if depth == 0:
                break
            continue
        # key position: after '{' or ',' inside an object, and followed by ':'
        nxt = _TOKEN.match(text, pos)
        while nxt and nxt.lastgroup == "ws":
            nxt = _TOKEN.match(text, nxt.end())
        is_key = nxt is not None and nxt.group(0) == ":" and prev_sig in ("{", ",")
        if kind == "str":
            js = _js_string_to_json(tok)
            sm = _SPLIT.match(text, pos)
            if sm:  # "a;b;c".split(";")  -> ["a","b","c"]
                parts = json.loads(js).split(json.loads(_js_string_to_json(sm.group(1))))
                out.append(json.dumps(parts))
                pos = sm.end()
            else:
                out.append(js)
        elif kind == "num":
            num = tok
            if num.startswith("."):
                num = "0" + num
            elif num.startswith("-."):
                num = "-0" + num[1:]
            if num.endswith("."):
                num += "0"
            if is_key:
                out.append('"' + num + '"')
            else:
                out.append(num)
        elif kind == "bang":
            out.append("true" if tok == "!0" else "false")
        elif kind == "ident":
            if is_key:
                out.append('"' + tok + '"')
            elif tok in ("true", "false", "null"):
                out.append(tok)
            elif tok in ("undefined", "NaN", "Infinity"):
                out.append("null")
            elif tok == "void":
                # 'void 0'
                m2 = _TOKEN.match(text, pos)
                while m2 and m2.lastgroup == "ws":
                    m2 = _TOKEN.match(text, m2.end())
                pos = m2.end()
                out.append("null")
            else:
                raise ValueError("Unsupported identifier %r in data at %d" % (tok, pos))
        prev_sig = tok
    return json.loads("".join(out)), pos


# ----------------------------------------------------------------------------------------
# Networking (tries curl_cffi -> system curl -> urllib)
# ----------------------------------------------------------------------------------------
class FetchError(Exception):
    pass


def _looks_blocked(status, body):
    if status in (403, 429, 503):
        return True
    head = body[:3000] if isinstance(body, str) else ""
    return "Just a moment" in head or "cf-chl" in head or "challenge-platform" in head


def _fetch_curl_cffi(url, referer):
    from curl_cffi import requests as creq  # optional dependency
    r = creq.get(url, impersonate="chrome", timeout=60,
                 headers={"Referer": referer} if referer else None)
    return r.status_code, r.text


def _fetch_system_curl(url, referer):
    exe = shutil.which("curl") or shutil.which("curl.exe")
    if not exe:
        raise FetchError("curl not found")
    cmd = [exe, "-sS", "-L", "--compressed", "-m", "60", "-A", UA,
           "-H", "Accept: text/html,application/json,application/javascript,*/*",
           "-H", "Accept-Language: en-US,en;q=0.9",
           "-w", "\n__STATUS__%{http_code}", url]
    if referer:
        cmd[1:1] = ["-e", referer]
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    p = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL, **kw)
    if p.returncode != 0:
        raise FetchError(p.stderr.decode("utf-8", "replace").strip() or "curl failed")
    raw = p.stdout.decode("utf-8", "replace")
    body, _, status = raw.rpartition("\n__STATUS__")
    return int(status or 0), body


def _fetch_urllib(url, referer):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9",
        **({"Referer": referer} if referer else {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


class WebSource:
    """Fetches from lastepochtools.com."""

    def __init__(self, log):
        self.log = log
        self.method = None

    def get(self, path, referer=None):
        url = path if path.startswith("http") else SITE + path
        methods = [("curl_cffi", _fetch_curl_cffi), ("curl", _fetch_system_curl),
                   ("urllib", _fetch_urllib)]
        if self.method:  # stick with whatever worked first
            methods.sort(key=lambda m: m[0] != self.method)
        errors = []
        for name, fn in methods:
            try:
                status, body = fn(url, referer)
            except ImportError:
                continue
            except Exception as e:  # noqa
                errors.append("%s: %s" % (name, e))
                continue
            if status == 200 and not _looks_blocked(status, body):
                if self.method != name:
                    self.log("  (downloading with %s)" % name)
                self.method = name
                return body
            errors.append("%s: HTTP %s%s" % (name, status,
                                             " (Cloudflare block)" if _looks_blocked(status, body) else ""))
        raise FetchError("Could not download %s\n    %s" % (url, "\n    ".join(errors)))


# ----------------------------------------------------------------------------------------
# Game data (affix / item / unique names), cached per data version
# ----------------------------------------------------------------------------------------
def build_tables(db_js, en_json):
    i = db_js.find("window.itemDB")
    if i < 0:
        raise ValueError("Item database not found in the downloaded data file.")
    item_db, _ = js_literal_to_python(db_js, db_js.index("{", i))
    names = json.loads(en_json)

    def nm(key):
        return (names.get(key) or "").replace("''", "'") if key else ""

    def stats(a):
        out = []
        for prop in a.get("affixProperties") or []:
            label = nm(prop.get("modDisplayNameKey"))
            if not label:
                continue
            mt = prop.get("modifierType")
            out.append({0: "+" + label, 1: "Increased " + label, 2: "More " + label}.get(mt, label))
        return ", ".join(out)

    affixes = {}
    for group in ("singleAffixes", "multiAffixes"):
        src = item_db.get("affixList", {}).get(group) or {}
        for a in (src.values() if isinstance(src, dict) else src):
            title = nm(a.get("affixTitleKey"))
            affixes[str(a["affixId"])] = {
                "name": nm(a.get("affixDisplayNameKey")) or nm(a.get("lootFilterOverrideNameKey")),
                "title": title,
                "stats": stats(a),
                "type": {0: "Prefix", 1: "Suffix"}.get(a.get("type"), str(a.get("type"))),
                "multi": group == "multiAffixes",
            }
    bases, subtypes = {}, {}
    il = item_db.get("itemList", {})
    for grp in ("equippable", "nonEquippable"):
        for b in (il.get(grp) or {}).values():
            bid = str(b.get("baseTypeId"))
            bases[bid] = nm(b.get("displayNameKey"))
            for s in (b.get("subItems") or {}).values():
                subtypes["%s-%s" % (bid, s.get("subTypeId"))] = nm(s.get("displayNameKey"))
    uniques = {}
    ul = (item_db.get("uniqueList") or {}).get("uniques") or {}
    for u in (ul.values() if isinstance(ul, dict) else ul):
        uniques[str(u["uniqueId"])] = {
            "name": nm(u.get("displayNameKey")), "baseTypeId": u.get("baseTypeId"),
            "isSet": bool(u.get("isSetItem")), "legendaryType": u.get("legendaryType", 0)}
    # Skill tree IDs (e.g. "mas54") -> skill names, from the root node's name key.
    skills = {}
    for key, value in names.items():
        m = re.fullmatch(r"Skills\.Skill_(.+)_0_Name", key)
        if m:
            skills[m.group(1)] = value.replace("''", "'")
    return {"affixes": affixes, "bases": bases, "subtypes": subtypes, "uniques": uniques,
            "skills": skills}


def _save_text(path, text):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        pass


def load_tables(source, page_html, log):
    m = re.search(r"/data/(version\d+)/db/js/[0-9a-f]+\.js", page_html)
    if not m:
        raise ValueError("Couldn't find the item database link in the planner page.")
    version = m.group(1)
    db_urls = re.findall(r"/data/%s/db/js/[0-9a-f]+\.js" % version, page_html)
    cache_key = "v4_%s_%s" % (version, os.path.basename(db_urls[0])[:12])
    cache_file = os.path.join(CACHE_DIR, cache_key + ".json")
    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            log("Using cached game data (%s)." % version)
            return json.load(f), version
    log("Downloading game data for %s (one-time, ~6 MB)..." % version)
    db_js = None
    for u in db_urls:
        text = source.get(u, SITE + "/planner/")
        if "window.itemDB" in text:
            db_js = text
            break
    if db_js is None:
        raise ValueError("None of the database files contained the item list.")
    en_json = source.get("/data/%s/i18n/full/en.json" % version, SITE + "/planner/")
    log("Parsing game data...")
    tables = build_tables(db_js, en_json)
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(tables, f)
    except OSError:
        pass
    return tables, version


# ----------------------------------------------------------------------------------------
# Main workflow
# ----------------------------------------------------------------------------------------
def parse_link(text):
    """Planner link -> (page path, code used for output file names).
      https://www.lastepochtools.com/planner/BEdypDY9 -> ("/planner/BEdypDY9", "BEdypDY9")
    Profile character links are handled by le_profile.py."""
    text = text.strip()
    m = re.search(r"planner/([A-Za-z0-9_-]+)", text)
    if m:
        return "/planner/" + m.group(1), m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{4,20}", text):
        return "/planner/" + text, text
    raise ValueError("That doesn't look like a Last Epoch Tools planner or profile character link.\n"
                     "Expected something like https://www.lastepochtools.com/planner/BEdypDY9 or\n"
                     "https://www.lastepochtools.com/profile/<player>/character/<character>")


def parse_build_code(text):
    return parse_link(text)[1]


_JS_NAME = r"([A-Za-z_$][\w$]*)"
_API = r"(/api/internal/[A-Za-z0-9_]+/)"


def _js_string_var(page, name):
    v = re.search(r"\b%s\s*=\s*(['\"`])((?:(?!\1).){1,200})\1" % re.escape(name), page)
    return v.group(2) if v else None


def find_data_urls(page):
    """API URLs the page fetches its build from, best first. The planner fetches
    /api/internal/planner_data/<key>, where <key> sits in a JavaScript variable whose name is
    not fixed (e.g. jsj34pii); other pages (profile characters) may use another endpoint."""
    found = []
    for m in re.finditer(_API + r"['\"`]\s*\+\s*" + _JS_NAME, page):      # '/api/.../' + NAME
        val = _js_string_var(page, m.group(2))
        if val:
            found.append(m.group(1) + val)
    for m in re.finditer(_API + r"\$\{\s*" + _JS_NAME + r"\s*\}", page):    # `/api/.../${NAME}`
        val = _js_string_var(page, m.group(2))
        if val:
            found.append(m.group(1) + val)
    found += [m.group(1) for m in re.finditer(r"(/api/internal/[A-Za-z0-9_]+/[A-Za-z0-9_\-/%.]+)", page)]
    # last resort for planner pages: a short inline variable holding a 32-character hex key
    m = re.search(r"\bvar\s+[A-Za-z_$][\w$]{2,15}\s*=\s*['\"]([0-9a-f]{32})['\"]", page)
    if m:
        found.append("/api/internal/planner_data/" + m.group(1))
    found.sort(key=lambda u: "planner_data" not in u)   # stable: planner_data first
    return list(dict.fromkeys(found))


def find_build_hash(page):
    """The planner_data key in a planner page (kept for compatibility)."""
    for u in find_data_urls(page):
        if "/planner_data/" in u:
            return u.rsplit("/", 1)[1]
    return None


def extract_build(obj):
    """Finds the planner-style build ({"bio", "equipment", ...}) in an API response and
    returns it wrapped as {"data": build, ...}, or None."""
    def search(o, depth=0):
        if depth > 6:
            return None
        if isinstance(o, dict):
            if "equipment" in o and ("bio" in o or "skillTrees" in o):
                return o
            for v in o.values():
                r = search(v, depth + 1)
                if r is not None:
                    return r
        elif isinstance(o, list):
            for v in o[:50]:
                r = search(v, depth + 1)
                if r is not None:
                    return r
        return None
    inner = search(obj)
    if inner is None:
        return None
    if isinstance(obj, dict) and obj.get("data") is inner:
        return obj
    return {"data": inner}


def _save_debug_page(code, page):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)   # only written when a download fails
        path = os.path.join(CACHE_DIR, "debug_page_%s.html" % code)
        with open(path, "w", encoding="utf-8") as f:
            f.write(page)
        return path
    except OSError:
        return None


def load_page_data(src, path, code, log, page=None):
    """Downloads the page at path (unless given) and the data it loads.
    Returns (page, data, build): data is the whole JSON answer (profile pages also list their
    snapshots there), build the planner-style part of it."""
    if page is None:
        log("Fetching %s..." % path)
        page = src.get(path)
    for url in find_data_urls(page):
        try:
            data = json.loads(src.get(url, SITE + path))
            build = extract_build(data)
        except (FetchError, ValueError) as e:
            logger.info("No build at %s (%s)", url, e)
            continue
        if build is not None:
            logger.info("Build data from %s", url)
            return page, data, build
    dbg = _save_debug_page(code, page)
    hints = []
    if "planner" not in page.lower() and "profile" not in page.lower():
        hints.append("the download doesn't look like a Last Epoch Tools page (possibly a "
                     "Cloudflare check page)")
    if "/data/version" not in page:
        hints.append("the page has no game-data links either")
    raise ValueError(
        "Couldn't find the build data in the downloaded page (%d characters)%s.\n"
        "The downloaded page was saved to:\n    %s\n"
        "Send that file to Claude to diagnose it." % (
            len(page), (": " + "; ".join(hints)) if hints else "", dbg or "(could not save)"))


def finish_build(src, path, code, page, build, log):
    """Loads game data and fills tree versions. Returns (code, build, tables, version)."""
    if not re.search(r"/data/version\d+/db/js/", page):   # game-data links live on the planner page
        page = src.get("/planner/", SITE + path)
    tables, version = load_tables(src, page, log)
    fill_tree_versions(build, src, page, version, log)
    return code, build, tables, version


def fetch_build(src, path, code, log, page=None):
    """Page -> build -> (code, build, tables, version). Shared by planner and profile links."""
    page, _, build = load_page_data(src, path, code, log, page)
    return finish_build(src, path, code, page, build, log)


def run_from_link(link, log):
    """Last Epoch Tools planner link -> (code, build, tables, version)."""
    path, code = parse_link(link)
    return fetch_build(WebSource(log), path, code, log)


# ----------------------------------------------------------------------------------------
# Skill tree versions. Planner builds carry each tree's "version"; profile characters don't,
# and the game ignores a skill tree whose version doesn't match (only version-0 trees worked).
# ----------------------------------------------------------------------------------------
# Seen in planner builds (data version 1.5.0); used when the site's data gives nothing better.
# Passive (character) tree per class index, and the Weaver tree, from LE Tools' 1.5.0 data.
CHAR_TREE_IDS = ["pr-1", "mg-1", "kn-1", "ac-1", "rg-1"]
KNOWN_TREE_VERSIONS_EXTRA = {"pr-1": 12, "mg-1": 7, "kn-1": 12, "ac-1": 3, "rg-1": 0, "weaver": 10}
# The game rejects a whole tree saved with an older version than its own, while a newer number
# loads fine. LE Tools' data lags for these, so never write less (ac-1: 3 failed, 4 and 5 loaded
# in game, Jake 2026-10-07).
MIN_TREE_VERSIONS = {"ac-1": 4}
KNOWN_TREE_VERSIONS = {"to50": 0, "ga2st": 1, "mas54": 3, "wc57": 1, "su3lem": 0, "ra1an": 0,
                       "sm87r4": 1, "hh7pa3": 0, "si4lgl": 5, "ah443": 2}
_TREE_VER_RX = [
    re.compile(r"""["']?treeID["']?\s*:\s*["']([\w-]+)["'][^{}\[\]]{0,400}?["']?version["']?\s*:\s*(\d+)"""),
    re.compile(r"""["']?version["']?\s*:\s*(\d+)[^{}\[\]]{0,400}?["']?treeID["']?\s*:\s*["']([\w-]+)["']"""),
]


def scan_tree_versions(text):
    out = {}
    for m in _TREE_VER_RX[0].finditer(text):
        out.setdefault(m.group(1), int(m.group(2)))
    for m in _TREE_VER_RX[1].finditer(text):
        out.setdefault(m.group(2), int(m.group(1)))
    return out


def load_tree_versions(src, page, version, log):
    """treeID -> version from the site's own scripts, cached per data version. The scripts are
    also kept in le_affix_cache/raw_<version>/ so they can be inspected if this finds nothing."""
    cache_file = os.path.join(CACHE_DIR, "tree_versions_v2_%s.json" % version)
    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)
    raw_dir = os.path.join(CACHE_DIR, "raw_%s" % version)
    _save_text(os.path.join(raw_dir, "planner_page.html"), page)
    found = scan_tree_versions(page)
    urls = re.findall(r"""(?:src|href)\s*=\s*["']((?:https://www\.lastepochtools\.com)?/[^"'?#]+\.js(?:on)?)""", page)
    for u in list(dict.fromkeys(urls))[:40]:
        if "/db/js/" in u or "/i18n/" in u:
            continue
        try:
            text = src.get(u, SITE + "/planner/")
        except FetchError as e:
            logger.info("Could not fetch %s (%s)", u, e)
            continue
        _save_text(os.path.join(raw_dir, re.sub(r"[^A-Za-z0-9_.-]", "_", u.split("lastepochtools.com")[-1])), text)
        found.update({k: v for k, v in scan_tree_versions(text).items() if k not in found})
    log("Skill tree versions found in site data: %d" % len(found))
    if found:
        _save_text(cache_file, json.dumps(found))
    return found


def fill_tree_versions(build, src, page, version, log):
    """Adds the missing "version" to the skill, passive and Weaver trees (profile characters
    lack them, and the game ignores a tree whose version doesn't match)."""
    data = build.get("data", build)
    bio = data.get("bio") or {}
    cls = bio.get("characterClass", build.get("class"))
    wanted = [(t, t["treeID"]) for t in data.get("skillTrees") or []
              if t.get("treeID") and "version" not in t]
    tree = data.get("charTree")
    if isinstance(tree, dict) and "version" not in tree and isinstance(cls, int) and 0 <= cls < len(CHAR_TREE_IDS):
        wanted.append((tree, CHAR_TREE_IDS[cls]))
    weaver = data.get("weaverTree")
    if isinstance(weaver, dict) and "version" not in weaver:
        wanted.append((weaver, "weaver"))
    if wanted:
        _lookup_tree_versions(wanted, src, page, version, log)
    # Raise outdated versions, including ones the planner build already carries.
    floors = [(t, t.get("treeID")) for t in data.get("skillTrees") or []]
    if isinstance(tree, dict) and isinstance(cls, int) and 0 <= cls < len(CHAR_TREE_IDS):
        floors.append((tree, CHAR_TREE_IDS[cls]))
    for obj, tid in floors:
        low = MIN_TREE_VERSIONS.get(tid)
        if low is not None and int(obj.get("version") or 0) < low:
            obj["version"] = low


def _lookup_tree_versions(wanted, src, page, version, log):
    try:
        site = load_tree_versions(src, page, version, log)
    except Exception:  # noqa - never let this stop a download
        logger.exception("Looking up tree versions failed")
        site = {}
    known = dict(KNOWN_TREE_VERSIONS, **KNOWN_TREE_VERSIONS_EXTRA)
    for obj, tid in wanted:
        if tid in site:
            obj["version"] = site[tid]
        elif tid in known:
            obj["version"] = known[tid]
        else:
            log("  Tree version unknown for %s - it may not load in game" % tid)
