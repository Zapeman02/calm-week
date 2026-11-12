# Calm Week

A calm weekly planner: drag blocks onto a week grid, auto-arrange your goals around fixed stuff, and sync the result to any calendar app that subscribes to `.ics` URLs (TimeTree, Apple Calendar, Google Calendar).

## Requirements
- macOS (the Dock app; the web UI runs anywhere with Python)
- Python 3 (no packages needed)
- [GitHub CLI](https://cli.github.com) logged in: `gh auth login` — used for calendar sync
- Optional: [Claude Code](https://claude.com/claude-code) CLI (`claude`) for "arrange with Claude"

## Run
```sh
./Calm\ Week.command
```
Or build the Dock app once (needs Xcode command line tools):
```sh
mac/build.sh
```
This creates `Calm Week.app` pointing at your clone. Drag it to the Dock.

## Your data stays local
On first run the app starts from `data/template.example.json`. Everything you change is saved locally and is gitignored:
- `data/template.json` — your categories, goals and settings
- `data/state.json` — your weeks
- `data/config.json` — TimeEdit URL and gist id

## Calendar sync
Sync uploads your calendar to a **secret gist** on your GitHub account. Secret means unlisted, not private: anyone with the link can read it. The gist also holds a `state.json` backup of your weeks. After the first sync, the calendar URL is saved as `rawUrl` in `data/config.json` — subscribe to it in your calendar app. To turn sync off, set `"sync": false` in `data/config.json`.

Lectures can be imported from a TimeEdit `.ics` link (Settings).

## Tests
```sh
./check.sh
```
