import json
import shutil
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from server import App
from week import apply_goal_changes, sync_goals, sync_protected, week_id_of

FIXTURE = Path(__file__).resolve().parent / "template.json"


class SyncGoalsTest(unittest.TestCase):
    NOW = "2026-10-07T12:00"

    def test_removed_goal_leaves_future_but_keeps_past(self):
        blocks = [
            {"id": "a", "type": "flexible", "goal": "old", "start": None},
            {"id": "b", "type": "flexible", "goal": "old", "start": "2026-10-08T10:00"},
            {"id": "h", "type": "flexible", "goal": "old", "start": "2026-10-05T10:00"},
            {"id": "c", "type": "protected", "goal": None, "start": "2026-10-05T12:00"},
        ]
        goals = [{"id": "walk", "title": "Walk", "category": "walk", "count": 2, "minutes": 60}]
        result = sync_goals(blocks, goals, self.NOW)
        self.assertEqual({b["id"] for b in result} & {"a", "b", "c", "h"}, {"c", "h"})
        self.assertEqual(sum(1 for b in result if b.get("goal") == "walk"), 2)

    def test_lower_count_and_new_length_apply_to_future(self):
        blocks = [
            {"id": "u", "type": "flexible", "goal": "run", "start": None, "title": "Running", "category": "run", "minutes": 120},
            {"id": "f", "type": "flexible", "goal": "run", "start": "2026-10-09T10:00", "title": "Running", "category": "run", "minutes": 120},
            {"id": "p", "type": "flexible", "goal": "run", "start": "2026-10-06T10:00", "title": "Running", "category": "run", "minutes": 120},
        ]
        goals = [{"id": "run", "title": "Bike", "category": "run", "count": 2, "minutes": 90}]
        result = {b["id"]: b for b in sync_goals(blocks, goals, self.NOW)}
        self.assertEqual(set(result), {"p", "f"})
        self.assertEqual((result["f"]["title"], result["f"]["minutes"]), ("Bike", 90))
        self.assertEqual(result["p"]["minutes"], 120)


class SaveKeepsPlanTest(unittest.TestCase):
    OLD = [{"id": "run", "title": "Running", "category": "run", "count": 2, "minutes": 120},
           {"id": "gone", "title": "Old", "category": "x", "count": 1, "minutes": 60}]
    BLOCKS = [
        {"id": "f", "type": "fixed", "goal": "run", "start": "2026-10-09T10:00", "title": "Running", "category": "run", "minutes": 120, "travelBefore": 0, "travelAfter": 0},
        {"id": "u", "type": "flexible", "goal": "run", "start": None, "title": "Running", "category": "run", "minutes": 120, "travelBefore": 0, "travelAfter": 0},
        {"id": "x", "type": "flexible", "goal": "gone", "start": "2026-10-09T15:00", "title": "Old", "category": "x", "minutes": 60, "travelBefore": 0, "travelAfter": 0},
    ]

    def test_unchanged_settings_change_nothing(self):
        self.assertEqual(apply_goal_changes(self.BLOCKS, self.OLD, self.OLD), self.BLOCKS)

    def test_deleted_tray_session_stays_deleted(self):
        blocks = [b for b in self.BLOCKS if b["id"] != "u"]
        self.assertEqual(apply_goal_changes(blocks, self.OLD, self.OLD), blocks)

    def test_only_changes_apply(self):
        new = [{"id": "run", "title": "Bike", "category": "run", "count": 1, "minutes": 90},
               {"id": "walk", "title": "Walk", "category": "walk", "count": 2, "minutes": 60}]
        result = apply_goal_changes(self.BLOCKS, self.OLD, new)
        ids = {b["id"] for b in result}
        self.assertEqual(ids & {"f", "u", "x"}, {"f", "x"})
        f = next(b for b in result if b["id"] == "f")
        self.assertEqual((f["title"], f["minutes"], f["start"]), ("Bike", 120, "2026-10-09T10:00"))
        self.assertEqual(sum(1 for b in result if b.get("goal") == "walk"), 2)

    def test_reset_counts_fixed_sessions(self):
        result = sync_goals(self.BLOCKS, self.OLD[:1], "2026-10-07T12:00")
        self.assertEqual(sum(1 for b in result if b.get("goal") == "run"), 2)


class SyncProtectedTest(unittest.TestCase):
    def test_moves_future_defaults_but_not_hand_moved_or_past(self):
        old = [{"title": "Dinner", "start": "18:00", "minutes": 45}]
        new = [{"title": "Dinner", "start": "19:00", "minutes": 60}]
        blocks = [
            {"id": "past", "type": "protected", "title": "Dinner", "start": "2026-10-06T18:00", "minutes": 45},
            {"id": "next", "type": "protected", "title": "Dinner", "start": "2026-10-08T18:00", "minutes": 45},
            {"id": "hand", "type": "protected", "title": "Dinner", "start": "2026-10-09T17:30", "minutes": 45},
        ]
        result = {b["id"]: (b["start"], b["minutes"]) for b in sync_protected(blocks, old, new, "2026-10-07T12:00")}
        self.assertEqual(result, {"past": ("2026-10-06T18:00", 45), "next": ("2026-10-08T19:00", 60),
                                  "hand": ("2026-10-09T17:30", 45)})


class SaveSettingsTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        shutil.copy(FIXTURE, self.dir / "template.json")
        (self.dir / "config.json").write_text(json.dumps({"sync": False}))
        self.app = App(self.dir)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_add_and_remove_goal_is_saved_to_files(self):
        goals = [g for g in self.app.settings()["goals"] if g["id"] != "hobby"] + [{"title": "Walk", "count": 1, "minutes": 60}]
        self.app.save_settings({"timeeditUrl": " https://example.com/x.ics ", "goals": goals, "dailyCapMinutes": 420})
        template = json.loads((self.dir / "template.json").read_text())
        titles = [g["title"] for g in template["goals"]]
        self.assertIn("Walk", titles)
        self.assertNotIn("Hobby", titles)
        walk = next(g for g in template["goals"] if g["title"] == "Walk")
        self.assertIn(walk["category"], template["categories"])
        self.assertEqual(json.loads((self.dir / "config.json").read_text())["timeeditUrl"], "https://example.com/x.ics")

    def test_activity_marked_free_time_marks_its_sessions(self):
        week_id = week_id_of(date.today())
        self.app.week(week_id)
        goals = self.app.settings()["goals"]
        goals[0]["noCap"] = True
        self.app.save_settings({**self.app.settings(), "goals": goals})
        blocks = [b for b in self.app.store.state["weeks"][week_id]["blocks"] if b.get("goal") == goals[0]["id"]]
        future = [b for b in blocks if not b["start"] or b["start"] >= datetime.now().strftime("%Y-%m-%dT%H:%M")]
        self.assertTrue(future and all(b.get("noCap") for b in future))

    def test_save_keeps_plan_and_reset_replans(self):
        week_id = week_id_of(date.today())
        self.app.week(week_id)
        state = self.app.store.state["weeks"][week_id]
        before = {b["id"]: b["start"] for b in state["blocks"]}
        goals = self.app.settings()["goals"]
        goals[0]["minutes"] += 60
        self.app.save_settings({**self.app.settings(), "goals": goals})
        after = {b["id"]: b["start"] for b in self.app.store.state["weeks"][week_id]["blocks"]}
        self.assertEqual(before, after)
        other = week_id_of(date.today() + timedelta(days=7))
        self.app.week(other)
        other_before = json.dumps(self.app.store.state["weeks"][other])
        self.app.reset_week(week_id)
        self.assertEqual(json.dumps(self.app.store.state["weeks"][other]), other_before)
        changed = [b for b in self.app.store.state["weeks"][week_id]["blocks"] if b.get("goal") == goals[0]["id"]
                   and (b["start"] is None or b["start"] >= datetime.now().strftime("%Y-%m-%dT%H:%M"))]
        self.assertTrue(all(b["minutes"] == goals[0]["minutes"] or b.get("fullMinutes") == goals[0]["minutes"] for b in changed))

    def test_default_travel_goes_on_new_sessions(self):
        goals = self.app.settings()["goals"] + [{"title": "Gym class", "count": 1, "minutes": 120, "travelBefore": 20, "travelAfter": 30}]
        self.app.save_settings({**self.app.settings(), "goals": goals})
        week_id = week_id_of(date.today())
        self.app.week(week_id)
        b = next(b for b in self.app.store.state["weeks"][week_id]["blocks"] if b["title"] == "Gym class")
        self.assertEqual((b["travelBefore"], b["travelAfter"]), (15, 30))

    def test_day_start_and_end(self):
        self.app.save_settings({**self.app.settings(), "placeStart": "09:00", "placeEnd": "20:00"})
        t = json.loads((self.dir / "template.json").read_text())
        self.assertEqual((t["placeStart"], t["placeEnd"], t["gridStart"]), ("09:00", "20:00", "08:00"))
        self.app.save_settings({**self.app.settings(), "placeStart": "20:00", "placeEnd": "09:00"})
        self.assertEqual(self.app.store.template["placeStart"], "09:00")

    def test_new_goal_is_added_to_current_week(self):
        week_id = week_id_of(date.today())
        self.app.week(week_id)
        goals = self.app.settings()["goals"] + [{"title": "Walk", "count": 2, "minutes": 60}]
        self.app.save_settings({"timeeditUrl": "", "goals": goals, "dailyCapMinutes": 420})
        blocks = self.app.store.state["weeks"][week_id]["blocks"]
        self.assertEqual(sum(1 for b in blocks if b["title"] == "Walk"), 2)
