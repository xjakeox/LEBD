"""Shared settings, logging and LE Tools ID decoding (lz-string)."""
import logging
import logging.handlers
import os
import sys
import threading


SITE = "https://www.lastepochtools.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")
APP_DIR = os.path.dirname(os.path.abspath(sys.argv[0] if sys.argv and sys.argv[0] else __file__))
CACHE_DIR = os.path.join(APP_DIR, "le_affix_cache")

LOG_FILE = os.path.join(APP_DIR, "le_affix_ids.log")
logger = logging.getLogger("le_affix_ids")


def setup_logging():
    """Rotating log file next to the script. Also catches uncaught errors, since a .pyw run
    under pythonw has no console to show them."""
    if logger.handlers:
        return
    logger.setLevel(logging.INFO)
    try:
        h = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3,
                                                 encoding="utf-8")
    except OSError:
        h = logging.NullHandler()   # folder not writable: carry on without a log file
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(h)
    sys.excepthook = lambda t, v, tb: logger.critical("Uncaught error", exc_info=(t, v, tb))
    threading.excepthook = lambda a: logger.critical(
        "Uncaught error in thread %s" % (a.thread.name if a.thread else "?"),
        exc_info=(a.exc_type, a.exc_value, a.exc_traceback))


def _console(msg=""):
    """print() that is safe under pythonw (no console) and also logs."""
    logger.info(msg)
    if sys.stdout is not None:
        try:
            print(msg)
        except (OSError, ValueError):
            pass


SLOT_NAMES = {
    "head": "Head", "chest": "Body", "hands": "Hands", "waist": "Belt", "feet": "Feet",
    "amulet": "Amulet", "ring1": "Ring 1", "ring2": "Ring 2", "relic": "Relic",
    "weapon1": "Weapon 1", "weapon2": "Weapon 2", "idol_altar": "Idol Altar",
}
SLOT_ORDER = ["head", "chest", "hands", "waist", "feet", "amulet", "ring1", "ring2",
              "relic", "weapon1", "weapon2", "idol_altar"]
EXTRA_AFFIX_FIELDS = [("sealedAffix", "Sealed"), ("primordialAffix", "Primordial"),
                      ("corruptedAffix", "Corrupted"), ("setAffix", "Set")]


# ----------------------------------------------------------------------------------------
# lz-string (decompressFromEncodedURIComponent) - LE Tools encodes IDs with this
# ----------------------------------------------------------------------------------------
_LZ_KEY = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+-$"


def lz_decompress_uri(s):
    s = s.replace(" ", "+")
    if not s:
        return ""
    vals = [_LZ_KEY.index(ch) for ch in s]
    length, reset = len(vals), 32
    state = {"val": vals[0], "pos": reset, "idx": 1}

    def bits(n):
        out, power = 0, 1
        for _ in range(n):
            r = state["val"] & state["pos"]
            state["pos"] >>= 1
            if state["pos"] == 0:
                state["pos"] = reset
                state["val"] = vals[state["idx"]] if state["idx"] < length else 0
                state["idx"] += 1
            if r:
                out |= power
            power <<= 1
        return out

    dictionary = {0: 0, 1: 1, 2: 2}
    enlarge, dict_size, num_bits = 4, 4, 3
    first = bits(2)
    if first == 2:
        return ""
    c = chr(bits(8 if first == 0 else 16))
    dictionary[3] = c
    w = c
    result = [c]
    while True:
        if state["idx"] > length:
            return ""
        code = bits(num_bits)
        if code in (0, 1):
            dictionary[dict_size] = chr(bits(8 if code == 0 else 16))
            dict_size += 1
            code = dict_size - 1
            enlarge -= 1
        elif code == 2:
            return "".join(result)
        if enlarge == 0:
            enlarge = 2 ** num_bits
            num_bits += 1
        if code in dictionary:
            entry = dictionary[code]
        elif code == dict_size:
            entry = w + w[0]
        else:
            return None
        result.append(entry)
        dictionary[dict_size] = w + entry[0]
        dict_size += 1
        enlarge -= 1
        w = entry
        if enlarge == 0:
            enlarge = 2 ** num_bits
            num_bits += 1


def decode_code(code):
    """'AKwFgjEA' -> ('A', '541').  First letter is the kind: A=affix, I=item, U=unique, S=set."""
    if not code or len(code) < 2:
        return None, None
    return code[0], lz_decompress_uri(code[1:])


def decode_affix_id(code):
    kind, digits = decode_code(code)
    if kind != "A" or not digits or not digits.isdigit():
        return None
    return int(digits)


def decode_item(code):
    """Returns dict with kind/baseTypeId/subTypeId/uniqueId (where known)."""
    kind, digits = decode_code(code)
    if not digits or not digits.isdigit():
        return {"kind": kind}
    if kind == "I" and len(digits) >= 9:
        # "1" + base(3) + subtype(3) + rarity(1) + uniqueId(2+)
        return {"kind": "I", "baseTypeId": int(digits[1:4]), "subTypeId": int(digits[4:7]),
                "rarity": int(digits[7]), "uniqueId": int(digits[8:] or 0)}
    if kind == "U" and len(digits) >= 6:
        # subtype(3) + uniqueId(3+)
        return {"kind": "U", "subTypeId": int(digits[:3]), "uniqueId": int(digits[3:])}
    return {"kind": kind}
