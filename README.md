# Last Epoch Build Downloader

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
- Equipped gear with its affixes
- Idols and the idol altar
- Blessings for all timelines, plus the Empowered Monolith unlock

## Requirements

- Windows with Last Epoch installed (Steam)
- [Python 3](https://www.python.org/downloads/) (3.12 or newer). Tick "Add Python to PATH" during install. No extra packages are needed.
- Optional: `pip install curl_cffi` makes downloads from Last Epoch Tools more reliable.

## How to use

1. Double-click `LastEpochBuildDownloader_V1.2.pyw`.
2. Paste a build link.
3. Enter a **Character name** (required).
4. Check the **Saves folder**. It is found automatically at
   `%USERPROFILE%\AppData\LocalLow\Eleventh Hour Games\Last Epoch\Saves`; use **Browse...** if yours is elsewhere.
5. Leave **New save file** as suggested (the next free `1CHARACTERSLOT_BETA_N`).
6. Click **Download Character** and pick a snapshot or gear set if asked.
7. A popup names the new save file. Start Last Epoch, choose **Offline**, and the character is in your list.

Existing saves are never overwritten; each download gets a new slot.

The **Build** and **Details / log** sections of the window are collapsed by default. Open them to see the build summary and the full item list with affix tiers.

## Deleting saves

**Delete Saves...** opens a list of your offline characters (file, name, level, class). Tick the ones to remove and confirm. The matching `.bak` backup is deleted too.

Note: if Steam Cloud is on for Last Epoch, Steam may download a deleted save again. If that happens, delete the character from inside the game instead.

## Troubleshooting

Everything the app does, including full error details, is written to `le_affix_ids.log` next to the app. If a download or a save fails, provide a copy of the log file and the build you were trying to pull from.

If a character does not load in game, also grab the game's log right after the failure:
`%USERPROFILE%\AppData\LocalLow\Eleventh Hour Games\Last Epoch\Player.log`

## AI Disclosure

This app was almost entirely produced by AI. Please report any bugs that are identified. 