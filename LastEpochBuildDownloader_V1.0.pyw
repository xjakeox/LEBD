#!/usr/bin/env python3
"""
Last Epoch Build Downloader - Season 5
--------------------------------------
Paste a Last Epoch Tools planner link (e.g. https://www.lastepochtools.com/planner/BEdypDY9)
or a profile character link (https://www.lastepochtools.com/profile/<player>/character/<name>;
a popup lists the character's days and events to pick from)
or a Maxroll planner link (https://maxroll.gg/last-epoch/planner/<id>; with several gear sets a
popup asks which one to download)
and get a game-ready offline character save. The log lists every equipped item and idol with
its affixes, tiers and the game's internal affix IDs.

The window also asks for a Character Name, the offline Saves folder (found automatically when
it is in the usual place) and the new save file's name (the next free 1CHARACTERSLOT_BETA_N),
then writes a game-ready character save built from the class template in OriginalCharacterFiles.

Usage:
    Double-click this file (.pyw: opens the window with no command prompt), or from a terminal:
        python LastEpochBuildDownloader_V1.0.pyw
            -> opens the window
        python LastEpochBuildDownloader_V1.0.pyw <link> [--name <character name>] [--saves <folder>]
            -> no window, prints the item list (and writes the save when --name is given)

Everything shown in the window, plus full error details, is also written to le_affix_ids.log
next to this file (rotated at 1 MB, 3 old copies kept).

The code lives in the le_downloader folder next to this file; keep the two together.

Only the Python standard library is required. If `curl_cffi` is installed
(pip install curl_cffi) it is used first, because it gets past Cloudflare most reliably.
"""
import sys

from le_downloader.common import _console, logger, setup_logging
from le_downloader.let_fetch import run_from_link
from le_downloader.items import export, format_summary
from le_downloader.save_writer import find_default_save_dir, next_save_file_name, write_character_save
from le_downloader.gui import run_gui
from le_downloader import le_profile, maxroll


def run_cli(args):
    log = _console
    try:
        import argparse
        ap = argparse.ArgumentParser(prog="LastEpochBuildDownloader_V1.0.pyw")
        ap.add_argument("link")
        ap.add_argument("--name", default="", help="character name for the new save")
        ap.add_argument("--saves", default=None, help="offline Saves folder (default: auto-detect)")
        ap.add_argument("--file", default=None, help="new save file name (default: next free slot)")
        opts = ap.parse_args(args)
        save_dir = find_default_save_dir() if opts.saves is None else opts.saves
        settings = {"character_name": opts.name, "save_dir": save_dir,
                    "save_file_name": opts.file or next_save_file_name(save_dir)}
        if maxroll.is_maxroll_link(opts.link):   # no popup here: uses the link's #n or the active set
            code, build, tables, version = maxroll.run_from_link(opts.link, log)
        elif le_profile.is_profile_link(opts.link):   # no popup here: the link's day/event or the newest
            code, build, tables, version = le_profile.run_from_link(opts.link, log)
        else:
            code, build, tables, version = run_from_link(opts.link, log)
        rows = export(code, build, tables, version, log, settings)
        _console()
        _console(format_summary(rows))
        if opts.name:
            write_character_save(build, rows, settings, log)
        else:
            _console("No --name given, so no character save was written.")
    except Exception as e:  # noqa
        logger.exception("Command-line run failed")
        _console("ERROR: %s" % e)
        sys.exit(1)


if __name__ == "__main__":
    setup_logging()
    logger.info("Started (%s)", " ".join(sys.argv))
    if len(sys.argv) > 1:
        run_cli(sys.argv[1:])
    else:
        try:
            run_gui()
        except ImportError:
            logger.exception("tkinter is not available")
            if sys.stdin is None:   # pythonw: no console to fall back to
                sys.exit(1)
            run_cli([input("Paste a Last Epoch Tools planner link: ")])
