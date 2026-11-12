# Calm Week — project summary for AI agents

Local weekly planner. A Python stdlib HTTP server (`BE/server.py`, port 8765, `CALM_PORT` overrides) serves a vanilla-JS UI (`FE/`) and a JSON API. No runtime dependencies; dev-only `.venv` holds Playwright for E2E tests.

## Layout
- `BE/server.py`: `Store` (JSON files in `data/`), `TimeEdit` (fetches lecture `.ics`, cached 1h), `Syncer` (debounced upload to a secret gist), `App` (API logic), `Handler` (routes under `/api/`: `heartbeat`, `week/<id>` GET/PUT, `arrange/<id>`, `claude/<id>`, `reset/<id>`, `settings` GET/PUT, `sync`). The server exits when the UI's heartbeat stops (`AUTO_EXIT_SECONDS`).
- `BE/week.py`: week ids (`YYYY-Www`), block creation, and merging goals, protected blocks and TimeEdit lectures into a week.
- `BE/scheduler.py`: `arrange()` places flexible goal blocks around fixed and protected ones (preferences, caps, conflicts, light day).
- `BE/claude.py`: "arrange with Claude". Runs the local `claude` CLI (`claude -p --model sonnet`) and validates its output.
- `BE/ics.py`: builds and parses `.ics`. `BE/gist.py`: uploads `calendar.ics` and a `state.json` backup through the `gh` CLI.
- `FE/app.js`: week grid, drag/resize, settings. `FE/api.js`: fetch wrapper.
- `mac/`: Swift WebView wrapper. `mac/build.sh` builds `Calm Week.app` with this clone's path in `Info.plist`. The built app is gitignored.

## Data (all user data is local and gitignored)
- `data/template.example.json`: the committed generic default. Used only when `data/template.json` is missing.
- `data/template.json`: the user's categories, goals, protected blocks and Claude wishes. Written by Settings.
- `data/state.json`: weeks to blocks. `data/config.json`: TimeEdit URL, sync flag, gist id and raw URL.
- Never commit personal data or real URLs. Keep the example template generic.

Built-in category ids that the code relies on: `lecture`, `free`, `meal`, `other`.

## Block model
`{id, title, category, type: fixed|flexible|protected|suggested, start: ISO local or null, minutes, travelBefore, travelAfter, skipped, goal}`. `suggested` blocks are TimeEdit lectures. They are not exported to `.ics`.

## Checks
`./check.sh` runs the unit tests (`BE/tests`, fixture `BE/tests/template.json`) and the Playwright UI tests (`e2e/`).
