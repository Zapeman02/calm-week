# Calm Week

A calm weekly planner. You tell it what you want to fit into a week (study 4×2h, workout 3×1h, …), it places those blocks around your lectures, meals and other fixed stuff, and the result shows up in your phone calendar (TimeTree, Apple Calendar, Google Calendar) through an `.ics` subscription.

Everything runs locally on your machine. The only thing that leaves it is the optional calendar sync to your own GitHub gist.

## How it works
- **Fixed** blocks never move (exams, labs, appointments).
- **Flexible** blocks come from your weekly activities (goals). **Rearrange** places them in free time, using your preferred time of day, allowed days, travel time and a daily cap.
- **Protected** blocks (lunch, dinner, evening free time) are never overwritten.
- **Lectures** can be imported from a TimeEdit `.ics` link. They show up as suggestions you can skip.
- **Ask Claude** (optional) lets Claude rearrange the week from a wish in plain text, like "keep Friday light".
- **Sync**: a few seconds after each change, the week is uploaded as `calendar.ics` to a secret gist on *your* GitHub account. Your calendar app subscribes to that URL and refreshes on its own.

## Requirements
- macOS for the Dock app. The web UI runs anywhere Python runs.
- Python 3. No packages needed.
- [GitHub CLI](https://cli.github.com), logged in with `gh auth login`. Needed for calendar sync only.
- Optional: the [Claude Code](https://claude.com/claude-code) CLI (`claude`), logged in. Needed for "Ask Claude" only.

## Install
```sh
git clone https://github.com/Zapeman02/calm-week.git
cd calm-week
mac/build.sh        # builds "Calm Week.app" for this folder (needs Xcode command line tools)
```
Drag `Calm Week.app` to the Dock. Without the app, run `./Calm\ Week.command`, or `python3 BE/server.py` and open http://localhost:8765.

The server starts with the app and stops on its own about 90 seconds after you close the window.

## Use it
1. **Settings → Activities.** Replace the example activities with your own: how many times a week, how long, which days, preferred time, and travel before/after. "Counts" adds the activity to the daily cap, "Free time" leaves it out.
2. **Settings → Day rhythm.** Set when the day starts, how late to plan, and the max planned time per day. The light day (Sunday by default) is set with `lightDay` in `data/template.json` (0 = Monday … 6 = Sunday).
3. **Settings → Connections** (optional). Paste your TimeEdit `.ics` link, and add standing wishes for Claude.
4. Press **Rearrange** to place everything. Anything that doesn't fit stays in **To place**.
5. Adjust by hand:
   - Drag on an empty spot to create a block.
   - Drag a block to move it. Drag its bottom edge to resize.
   - Drag an item from **To place** onto the grid.
   - Click a block to rename it, change its category, switch it between Fixed and Flexible, set travel time, split it, duplicate it or delete it.
6. **Ask Claude** for a rearrangement with a wish for this week. The result is applied right away. **Undo** (⌘Z) takes it back.
7. Use **‹ ›** or the arrow keys to switch weeks, and **Today** to jump back. **Reset this week** (in Settings) re-plans the week you're looking at from your defaults.

## Get it into TimeTree (or another calendar)
1. Make one change in the app. The first sync creates your gist through `gh`.
2. Open `data/config.json` and copy the `rawUrl` value. It looks like `https://gist.githubusercontent.com/<you>/<id>/raw/calendar.ics`.
3. In TimeTree, add a calendar subscription (an external calendar or iCal URL) and paste that URL. Apple and Google Calendar call it "subscribe to a calendar by URL".

The calendar app polls the URL, so changes can take from minutes to a few hours to show up, depending on the app. Meals are left out of the export by default (`exportExclude` in your template).

**Privacy:** a secret gist is unlisted, not private. Anyone with the link can read it. The gist also holds a `state.json` backup of your weeks, including imported lecture titles. To turn sync off, set `"sync": false` in `data/config.json`.

## Your data stays local
On first run the app starts from `data/template.example.json`. Everything you change is saved locally, and all of it is gitignored:
- `data/template.json`: your activities, categories and settings
- `data/state.json`: your weeks
- `data/config.json`: TimeEdit link, sync on/off, and your gist id and URL

## Development
```sh
./check.sh   # unit tests + Playwright UI tests (UI tests need .venv with playwright)
```
See `CLAUDE.md` for a code map.
