import json
import os
import re
import threading
import time
import uuid
from datetime import date, datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

import claude
import gist
import ics
from scheduler import FITS, arrange, fit_of
from week import DAY, hm, join_parts, monday_of, merge_suggested, new_week, apply_goal_changes, reset_protected, sync_goals, sync_protected, to_minutes, week_id_of

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("CALM_DATA", ROOT / "data"))
PORT = int(os.environ.get("CALM_PORT", "8765"))
AUTO_EXIT_SECONDS = 90
SYNC_DELAY_SECONDS = 5
SYNC_RETRY_SECONDS = 60
TIMEEDIT_MAX_AGE_SECONDS = 3600
WEEK_ID = re.compile(r"^\d{4}-W\d{2}$")
CLOCK = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
PREFER = re.compile(r"^(any|morning|afternoon|evening|\d{2}:\d{2}-\d{2}:\d{2})$")
DEFAULT_CONFIG = {"timeeditUrl": "", "sync": True, "gistId": "", "rawUrl": ""}
NEW_COLORS = ["#7f9fa8", "#a89a6e", "#8e9ebc", "#9c8a7a", "#7d9a8f", "#b0899a", "#8a8fb5", "#a3a07a"]


class Store:
    def __init__(self, data_dir):
        self.dir = data_dir
        self.lock = threading.RLock()
        template_path = data_dir / "template.json"
        self.template = json.loads((template_path if template_path.exists() else ROOT / "data" / "template.example.json").read_text())
        self.state = self._read("state.json", {"weeks": {}})
        self.config = {**DEFAULT_CONFIG, **self._read("config.json", {})}

    def _read(self, name, default):
        path = self.dir / name
        return json.loads(path.read_text()) if path.exists() else default

    def _write(self, name, data):
        tmp = self.dir / f".{name}.tmp"
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False))
        tmp.replace(self.dir / name)

    def save_state(self):
        with self.lock:
            self._write("state.json", self.state)

    def save_config(self):
        with self.lock:
            self._write("config.json", self.config)

    def save_template(self):
        with self.lock:
            self._write("template.json", self.template)


class TimeEdit:
    def __init__(self, store):
        self.store = store
        self.events = []
        self.fetched = 0

    def reset(self):
        self.events = []
        self.fetched = 0

    def current_events(self):
        url = self.store.config["timeeditUrl"]
        if url and time.time() - self.fetched > TIMEEDIT_MAX_AGE_SECONDS:
            try:
                with urlopen(url, timeout=8) as response:
                    self.events = ics.parse(response.read().decode("utf-8", "replace"))
                self.fetched = time.time()
            except OSError:
                pass
        return self.events


class Syncer:
    def __init__(self, store):
        self.store = store
        self.lock = threading.Lock()
        self.timer = None
        self.dirty = False
        self.last = None
        self.error = None

    def schedule(self, delay=SYNC_DELAY_SECONDS):
        if not self.store.config["sync"]:
            return
        self.dirty = True
        if self.timer:
            self.timer.cancel()
        self.timer = threading.Timer(delay, self.run)
        self.timer.daemon = True
        self.timer.start()

    def run(self):
        if not self.store.config["sync"]:
            return
        with self.lock:
            try:
                text = ics.build(self._exportable())
                config = self.store.config
                with self.store.lock:
                    backup = json.dumps(self.store.state, indent=1, ensure_ascii=False)
                gist_id = gist.upload(text, backup, config["gistId"])
                if gist_id != config["gistId"] or not config["rawUrl"]:
                    config["gistId"] = gist_id
                    config["rawUrl"] = gist.raw_url(gist_id)
                    self.store.save_config()
                self.dirty = False
                self.last = datetime.now().isoformat(timespec="seconds")
                self.error = None
            except Exception as e:
                self.error = str(e)[:200]
                self.schedule(SYNC_RETRY_SECONDS)

    def flush(self):
        if self.dirty:
            self.run()

    def _exportable(self):
        exclude = set(self.store.template["exportExclude"])
        with self.store.lock:
            return [b for wk in self.store.state["weeks"].values() for b in wk["blocks"]
                    if b["start"] and not b["skipped"] and b["type"] != "suggested" and b["category"] not in exclude]

    def status(self):
        return {"enabled": self.store.config["sync"], "last": self.last, "error": self.error, "url": self.store.config["rawUrl"]}


class App:
    def __init__(self, data_dir):
        self.store = Store(data_dir)
        self.timeedit = TimeEdit(self.store)
        self.syncer = Syncer(self.store)
        self.last_beat = None

    def week(self, week_id):
        monday = monday_of(week_id)
        events = self.timeedit.current_events()
        with self.store.lock:
            weeks = self.store.state["weeks"]
            created = week_id not in weeks
            if created:
                weeks[week_id] = new_week(week_id, self.store.template)
            wk = weeks[week_id]
            if self.store.config["timeeditUrl"]:
                wk["blocks"] = merge_suggested(wk["blocks"], events, monday)
            if created:
                wk["blocks"] = arrange(wk["blocks"], self.store.template, monday)
            self.store.save_state()
        if created:
            self.syncer.schedule()
        return self.payload(week_id)

    def save(self, week_id, blocks):
        with self.store.lock:
            self.store.state["weeks"][week_id] = {"blocks": blocks}
            self.store.save_state()
        self.syncer.schedule()
        return self.payload(week_id)

    def rearrange(self, week_id):
        with self.store.lock:
            wk = self.store.state["weeks"][week_id]
            wk["blocks"] = arrange(wk["blocks"], self.store.template, monday_of(week_id), replan=True)
            self.store.save_state()
        self.syncer.schedule()
        return self.payload(week_id)

    def ask_claude(self, week_id, wish):
        """Claude's times are checked by the normal scheduler, which re-places anything that breaks a rule."""
        monday = monday_of(week_id)
        now = datetime.now()
        cutoff = now.strftime("%Y-%m-%dT%H:%M")
        with self.store.lock:
            blocks = join_parts([dict(b) for b in self.store.state["weeks"][week_id]["blocks"]], cutoff)
        plans, meals = claude.suggest(blocks, self.store.template, monday, now, wish)
        busy = [b for b in blocks if b["start"] and not b["skipped"] and b["type"] not in ("flexible",)]
        for b in blocks:
            start = meals.get(b["id"])
            if start and not any(o is not b and overlaps(start, b["minutes"], o) for o in busy):
                b["movedFrom"], b["start"] = b["start"], start
        extra = []
        for b in blocks:
            parts = plans.get(b["id"])
            if parts is None or (b["start"] and b["start"] < cutoff) or any(s < cutoff for s, _ in parts):
                continue
            full = b["minutes"]
            b["start"], b["minutes"] = parts[0] if parts else (None, full)
            if b["minutes"] != full:
                b["fullMinutes"] = full
            if len(parts) == 2:
                start, minutes = parts[1]
                extra.append({**b, "id": uuid.uuid4().hex[:8], "start": start, "minutes": minutes, "partOf": b["id"], "travelBefore": 0})
                b["travelAfter"] = 0
        # Claude may go a little over the daily cap; Rearrange stays strict.
        return {"blocks": arrange(blocks + extra, self.store.template, monday, cap_slack=claude.CAP_SLACK)}

    def settings(self):
        t = self.store.template
        goals = [{"id": g["id"], "title": g["title"], "count": g["count"], "minutes": g["minutes"],
                  "days": [d for d in g.get("days", range(7)) if d != t["lightDay"] or g.get("lightOk")],
                  "prefer": g.get("prefer", "any"), "priority": g.get("priority", 2), "fit": fit_of(g), "noCap": g.get("noCap", False),
                  "travelBefore": g.get("travelBefore", 0), "travelAfter": g.get("travelAfter", 0), "color": t["categories"][g["category"]]["color"]} for g in t["goals"]]
        return {"timeeditUrl": self.store.config["timeeditUrl"], "dailyCapMinutes": t.get("dailyCapMinutes", 420),
                "claudeWishes": t.get("claudeWishes", ""), "goals": goals,
                "placeStart": t["placeStart"], "placeEnd": t["placeEnd"],
                "protected": [{"title": p["title"], "start": p["start"], "minutes": p["minutes"]} for p in t["protected"]]}

    def save_settings(self, data):
        with self.store.lock:
            url = data["timeeditUrl"].strip()
            if url != self.store.config["timeeditUrl"]:
                self.store.config["timeeditUrl"] = url
                self.store.save_config()
                self.timeedit.reset()
                if not url:
                    for wk in self.store.state["weeks"].values():
                        wk["blocks"] = [b for b in wk["blocks"] if b["type"] != "suggested"]
            old_goals = [dict(g) for g in self.store.template["goals"]]
            self.store.template["goals"] = [self._goal(g) for g in data["goals"] if g["title"].strip()]
            self.store.template["claudeWishes"] = claude.clean(data.get("claudeWishes", ""))
            start, end = data.get("placeStart", ""), data.get("placeEnd", "")
            if CLOCK.match(start) and CLOCK.match(end) and start < end:
                hour = max(0, hm(start) - 60) // 60
                self.store.template.update(placeStart=start, placeEnd=end, gridStart=f"{hour:02d}:00")
            old_protected = [dict(p) for p in self.store.template["protected"]]
            for p, d in zip(self.store.template["protected"], data.get("protected", [])):
                if CLOCK.match(d.get("start", "")):
                    p["start"] = d["start"]
                p["minutes"] = max(15, min(360, int(d.get("minutes", p["minutes"])) // 15 * 15))
            self.store.template["dailyCapMinutes"] = max(60, min(900, int(data["dailyCapMinutes"]) // 30 * 30))
            self.store.save_template()
            now = datetime.now().strftime("%Y-%m-%dT%H:%M")
            for _, wk in self._open_weeks():
                blocks = sync_protected(wk["blocks"], old_protected, self.store.template["protected"], now)
                wk["blocks"] = apply_goal_changes(blocks, old_goals, self.store.template["goals"])
            self.store.save_state()
        self.syncer.schedule()
        return self.settings()

    def reset_week(self, week_id):
        """One week goes back to the defaults from now on: meals at their times, sessions re-planned."""
        with self.store.lock:
            now = datetime.now().strftime("%Y-%m-%dT%H:%M")
            t = self.store.template
            wk = self.store.state["weeks"][week_id]
            blocks = reset_protected(join_parts(wk["blocks"], now), t["protected"], now)
            wk["blocks"] = arrange(sync_goals(blocks, t["goals"], now), t, monday_of(week_id), replan=True)
            self.store.save_state()
        self.syncer.schedule()
        return self.payload(week_id)

    def _open_weeks(self):
        this_monday = monday_of(week_id_of(date.today()))
        return [(week_id, wk) for week_id, wk in self.store.state["weeks"].items() if monday_of(week_id) >= this_monday]

    def _goal(self, data):
        """Keep scheduling rules of known goals; new ones get their own category and any day."""
        t = self.store.template
        old = next((g for g in t["goals"] if g["id"] == data.get("id")), None)
        days = sorted({int(d) for d in data.get("days", range(7)) if 0 <= int(d) < 7}) or list(range(7))
        rules = {"title": data["title"].strip(), "count": max(1, min(14, int(data["count"]))),
                 "minutes": max(30, min(480, int(data["minutes"]) // 30 * 30)), "days": days,
                 "prefer": data.get("prefer") if PREFER.match(data.get("prefer", "")) else "any",
                 "priority": data.get("priority") if data.get("priority") in (1, 2, 3) else 2,
                 "fit": data.get("fit") if data.get("fit") in FITS else "flex",
                 "noCap": data.get("noCap") is True,
                 **{k: max(0, min(120, int(data.get(k, 0)) // 15 * 15)) for k in ("travelBefore", "travelAfter")},
                 "lightOk": t["lightDay"] in days}
        if old:
            t["categories"][old["category"]]["name"] = rules["title"]
            return {**{k: v for k, v in old.items() if k != "split"}, **rules}
        goal_id = "g" + os.urandom(4).hex()
        used = {c["color"] for c in t["categories"].values()}
        color = next((c for c in NEW_COLORS if c not in used), NEW_COLORS[len(t["categories"]) % len(NEW_COLORS)])
        t["categories"][goal_id] = {"name": rules["title"], "color": color}
        return {"id": goal_id, "category": goal_id, **rules}

    def payload(self, week_id):
        monday = monday_of(week_id)
        now_offset = to_minutes(datetime.now().strftime("%Y-%m-%dT%H:%M"), monday)
        t = self.store.template
        return {
            "id": week_id,
            "monday": monday.isoformat(),
            "prev": week_id_of(monday - timedelta(days=7)),
            "next": week_id_of(monday + timedelta(days=7)),
            "current": week_id_of(date.today()),
            "isPast": now_offset >= 7 * DAY,
            "blocks": self.store.state["weeks"][week_id]["blocks"],
            "template": {k: t[k] for k in ("gridStart", "gridEnd", "lightDay", "categories")},
            "sync": self.syncer.status(),
        }


def overlaps(start, minutes, other):
    a = datetime.fromisoformat(start)
    b = datetime.fromisoformat(other["start"]) - timedelta(minutes=other["travelBefore"])
    return a < b + timedelta(minutes=other["minutes"] + other["travelBefore"] + other["travelAfter"]) and b < a + timedelta(minutes=minutes)


class Handler(SimpleHTTPRequestHandler):
    app = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "FE"), **kwargs)

    def log_message(self, *args):
        pass

    def end_headers(self):
        # Safari otherwise keeps old app files after an update.
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _route(self, method):
        parts = self.path.split("?")[0].strip("/").split("/")
        if parts[0] != "api":
            return False
        self.app.last_beat = time.time()
        name, arg = (parts + [None, None])[1:3]
        if arg == "current":
            arg = week_id_of(date.today())
        if arg is not None and not WEEK_ID.match(arg):
            self._json({"error": "bad week id"}, 400)
            return True
        if method == "GET" and name == "heartbeat":
            self._json(self.app.syncer.status())
        elif method == "GET" and name == "week" and arg:
            self._json(self.app.week(arg))
        elif method == "PUT" and name == "week" and arg:
            length = int(self.headers.get("Content-Length", 0))
            self._json(self.app.save(arg, json.loads(self.rfile.read(length))["blocks"]))
        elif method == "POST" and name == "arrange" and arg:
            self._json(self.app.rearrange(arg))
        elif method == "POST" and name == "claude" and arg:
            length = int(self.headers.get("Content-Length", 0))
            wish = json.loads(self.rfile.read(length) or b"{}").get("wish", "")
            try:
                self._json(self.app.ask_claude(arg, wish))
            except Exception as e:
                self._json({"error": str(e)[:200]}, 502)
        elif method == "POST" and name == "reset" and arg:
            self._json(self.app.reset_week(arg))
        elif method == "GET" and name == "settings":
            self._json(self.app.settings())
        elif method == "PUT" and name == "settings":
            length = int(self.headers.get("Content-Length", 0))
            self._json(self.app.save_settings(json.loads(self.rfile.read(length))))
        elif method == "POST" and name == "sync":
            self.app.syncer.run()
            self._json(self.app.syncer.status())
        else:
            self._json({"error": "not found"}, 404)
        return True

    def do_GET(self):
        if not self._route("GET"):
            super().do_GET()

    def do_PUT(self):
        self._route("PUT")

    def do_POST(self):
        self._route("POST")


def watch_heartbeat(app, server):
    while True:
        time.sleep(5)
        if app.last_beat and time.time() - app.last_beat > AUTO_EXIT_SECONDS:
            app.syncer.flush()
            server.shutdown()
            return


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    Handler.app = App(DATA)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=watch_heartbeat, args=(Handler.app, server), daemon=True).start()
    print(f"Calm Week on http://localhost:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
