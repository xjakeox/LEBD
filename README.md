# Last Epoch Build Downloader

**Version V1.3.1** (Season 5)

Turn a build you find online into a character you can load and play in Last Epoch's **offline mode**, so you can try a build before committing to it.

Paste a build link, type a character name, click **Download Character**, and a new offline save appears in your game's character list with the build's class, mastery, level, passives, skills, gear, idols and blessings already in place.

## Supported links

| Site | Example link |
|---|---|
| Last Epoch Tools planner | `https://www.lastepochtools.com/planner/BEdypDY9` |
| Last Epoch Tools profile character | `https://www.lastepochtools.com/profile/<player>/character/<name>` |
| Maxroll planner | `https://maxroll.gg/last-epoch/planner/<id>` |

- **Profile characters:** a popup lists the character's days and events (for example "Day 3" or a boss kill), newest first, so you can choose which snapshot to download.
- **Maxroll planners:** if the planner has several gear sets (for example Starting, Endgame, Aspirational), a popup asks which one to use.

## What gets copied into the save

- Character name, class, mastery and level
- Passive tree
- All five specialized skill trees and the skill hotbar
- Equipped gear with its affixes and their tiers. Profile characters also keep the real rolls of every affix, implicit and unique mod, so stats match the website; planner and Maxroll builds get perfect rolls
- Idols and the idol altar
- Blessings for all timelines, plus the Empowered Monolith unlock
- Timeline corruption on every empowered monolith (see [Timeline corruption](#timeline-corruption))

The new character starts from a clean class template, so starter items from that template stay in the inventory. Where the build has gear for a slot, the build's item is equipped instead of the starter item.

## Requirements

- Windows with Last Epoch installed (Steam)
- [Python 3](https://www.python.org/downloads/) (3.12 or newer). Tick "Add Python to PATH" during install. No extra packages are needed.
- Optional: `pip install curl_cffi` makes downloads from Last Epoch Tools more reliable.

## Files

Keep these together in one folder:

```
LastEpochBuildDownloader_V1.3.1.pyw    the app (double-click this)
LastEpochBuildDownloader.ico          window and taskbar icon
le_downloader\                        the app's code
OriginalCharacterFiles\               clean save templates for each class (never edited)
```

## How to use

1. Double-click `LastEpochBuildDownloader_V1.3.1.pyw`.
2. Paste a build link.
3. Enter a **Character name** (required).
4. Check the **Saves folder**. It is found automatically at
   `%USERPROFILE%\AppData\LocalLow\Eleventh Hour Games\Last Epoch\Saves`; use **Browse...** if yours is elsewhere.
5. Leave **New save file** as suggested (the next free `1CHARACTERSLOT_BETA_N`).
6. Tick **Hardcore** and/or **Solo Character Found (SCF)** if you want that mode; leave both off for a normal character. Pick the **Environment**: Seasonal (the default) or Legacy.
7. Set **Timeline Corruption** (100 by default, anything from 100 to 100000). See below.
8. Click **Download Character** and pick a snapshot or gear set if asked.
9. A popup names the new save file. Start Last Epoch, choose **Offline**, and the character is in your list.

Existing saves are never overwritten; each download gets a new slot.

The **Build** and **Details / log** sections of the window are collapsed by default. Open them to see the build summary and the full item list with affix tiers (and, for profile characters, each affix's roll as a percentage, for example `5 (78%)`).

## Timeline corruption

The **Timeline Corruption** box sets the corruption of the empowered monolith on all 10 timelines, so the character can go straight into the monolith at the difficulty you want to test.

- Type a whole number from **100** (the default) to **100000**. Anything outside that range shows a warning and nothing is downloaded until you fix it.
- The same value goes on every timeline. The character's highest corruption is set to it as well.
- Each download uses the value in the box. To try the build at another corruption, download it again to a new save.
- The command line has no corruption option and leaves the monoliths at the class template's corruption; use the window to set it.

## Deleting saves

**Delete Saves...** opens a list of your offline characters (file, name, level, class). Tick the ones to remove and confirm. The matching `.bak` backup is deleted too.

Note: if Steam Cloud is on for Last Epoch, Steam may download a deleted save again. If that happens, delete the character from inside the game instead.

## Command line (optional)

```
python LastEpochBuildDownloader_V1.3.1.pyw <link> --name "My Character"
```

Without `--name` it only prints the build's item list. `--hardcore` and `--scf` set the character's mode. `--saves <folder>` and `--file <name>` override the Saves folder and file name. Profile and Maxroll links use the snapshot or set in the link (or the newest/active one) with no popup.

## Troubleshooting

Everything the app does, including full error details, is written to `le_affix_ids.log` next to the app. If a download or a save fails, that log is the first place to look.

If a character does not load in game, also grab the game's log right after the failure:
`%USERPROFILE%\AppData\LocalLow\Eleventh Hour Games\Last Epoch\Player.log`

## AI Disclaimer
Yes, this was built using AI. No, (for the most part) I do not know what I am doing. I know minimal coding, enough to just get by, but couldn't have made this on my own. I made this for me, but figured some other people might find use in it.
