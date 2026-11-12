# Calm Week — weekly planner that syncs to TimeTree

## Context
Goal: a stupid-simple, calming desktop week planner that reduces stress and gives a feeling of control.
Drag/drop blocks, auto-arrange the loose stuff around the fixed stuff, and have it show up in TimeTree
automatically (TimeTree has no API since 2023, but it subscribes to `.ics` URLs — same trick as TimeEdit).
Obsidian-like vibe: dark, muted, spacious, chunky "Scratch-like" blocks snapping to a 30-min grid.

## Stack (no runtime dependencies)
- Frontend: plain HTML/CSS/vanilla JS, own week grid (no calendar lib), pointer events for drag/resize.
- Backend: Python 3 stdlib `http.server` — saves JSON, runs scheduler, fetches TimeEdit, uploads via `gh`.
- Window: `Calm Week.command` (double-click) → starts server, opens Chromium `--app=http://localhost:8765`.
  Safari alternative: open the URL and use File → Add to Dock.
- Server auto-exits ~60 s after the window closes (page sends a heartbeat). Close window = done.
- Sync: `.ics` → secret GitHub Gist via `gh api` (uses existing `gh` login, no token handling).
  TimeTree subscribes once to the Gist raw URL `https://gist.githubusercontent.com/<user>/<id>/raw/calendar.ics`.
  Lag up to TimeTree's refresh interval (accepted, < 1 day).

## Block types
| Type | Source | Auto-arrange |
|---|---|---|
| Fixed | manual (exam, mandatory lab, known club slot) | never moves |
| Suggested | TimeEdit import | stays at its time; one click "skip" frees the slot (dimmed) |
| Flexible | weekly goals template | placed/moved by auto-arrange |
| Protected | free time 21:00–00:00 daily, lunch 12:00–12:45, dinner 18:00–18:45 | never moves, never overwritten |

Any block can have travel before/after (shown as a faded tail, moves with the block, counted as occupied).

## Default week (example in `data/template.example.json`, your copy in `data/template.json`)
- Grid shows 07:00–00:00. Auto-arrange only places between 08:30–21:00.
- Light day: Sunday (only goals marked light-ok, e.g. a workout or hobby).
- Goals (example): study 4×2h (Mon–Fri) · workout 3×1h · hobby 1×2h · chores 1×1.5h (weekend).
- Rules: max one session per category per day, optional conflicts (two categories never on the same day),
  spread sessions across the week, keep a 15-min gap between blocks.

## Data
`data/state.json`:
```json
{ "weeks": { "2026-W41": { "blocks": [ { "id", "title", "category", "type",
  "start": "2026-10-07T10:00", "minutes": 120, "travelBefore": 0, "travelAfter": 0, "skipped": false } ] } } }
```
`data/template.json` (goals, windows, light day, categories+colors), `config.json` (TimeEdit URL, gist id — not secrets).
New week = template applied automatically when first opened. ‹ › arrows switch weeks; only one week visible.

## Files
- `server.py` — HTTP routes: `GET/PUT /api/week/<id>`, `POST /api/arrange/<id>`, `POST /api/sync`, `GET /api/heartbeat`; debounced auto-sync after save.
- `scheduler.py` — greedy placement: build occupied intervals (fixed, suggested-not-skipped, protected, travel) → place flexible goals longest-first, spread across days, preferred windows, rules above. Unplaceable goals stay in the side tray (never forced).
- `ics.py` — build `.ics` (stdlib, Europe/Stockholm, stable UIDs) + parse TimeEdit `.ics` (line folding, TZ).
- `gist.py` — create secret gist first time (store id in config), then `gh api -X PATCH gists/<id>`.
- `static/index.html`, `static/style.css`, `static/app.js` (grid, drag/resize, tray, undo), `static/api.js`.
- `Calm Week.command` — launcher.
- `tests/` — `test_scheduler.py`, `test_ics.py`; `e2e/test_ui.py` (Playwright, chromium + webkit).
- `check.sh` — runs pytest + Playwright.

## UI (calm by design)
- Top line: "This week: 18/19 goals placed · free time protected · synced 2 min ago".
- Week grid center, side tray with unplaced goals (drag into grid), one main button: **Rearrange**.
- Muted category colors, no red, soft animations when blocks move, Undo (Ctrl+Z) for everything.
- Click block → tiny popover: title, type (fixed/flexible), travel before/after, delete. No forms elsewhere.

## Build order (first draft, skip what's hard)
0. Create `calm-week/` and copy this plan to `calm-week/PLAN.md`.
1. Grid + manual blocks (create, drag, resize, delete) + persistence + week arrows.
2. Template + tray + protected blocks + scheduler + Rearrange + undo.
3. TimeEdit import as suggested blocks + skip.
4. `.ics` + Gist sync + launcher + auto-shutdown. User adds Gist URL in TimeTree once.
5. Tests + `check.sh`.

Later (not v1): settings panel for template, Claude integration ("lighter week"), Tauri wrapper.

## Needs user approval during build
- Create venv and install `pytest`, `pytest-playwright` + Playwright browsers (dev only).
- `git init` + create private GitHub repo with `gh repo create --private`.
- First `gh gist create --secret` (publishes calendar to a secret URL).
- User provides the TimeEdit `.ics` link.

## Verification
- `./check.sh`: scheduler tests (no overlaps, protected/fixed untouched, light-day rule, weekday-only study, travel counted), ICS round-trip, Playwright: drag block, Rearrange, Undo, week switch.
- Run app via launcher, Playwright screenshots of desktop window, inspect and fix visuals.
- Sync once, open Gist raw URL, validate `.ics` loads; subscribe in TimeTree and confirm events appear.
- Close window → confirm server exits.
