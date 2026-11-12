import json
import unittest
from datetime import datetime
from pathlib import Path

from scheduler import arrange
from week import DAY, make_block, monday_of, new_week, to_minutes

TEMPLATE = json.loads((Path(__file__).resolve().parent / "template.json").read_text())
WEEK = "2026-W41"
MONDAY = monday_of(WEEK)
BEFORE_WEEK = datetime(2026, 10, 1, 12, 0)


def span(b):
    start = to_minutes(b["start"], MONDAY)
    return start - b["travelBefore"], start + b["minutes"] + b["travelAfter"]


def placed(blocks, category=None):
    return [b for b in blocks if b["type"] == "flexible" and b["start"] and (category is None or b["category"] == category)]


def day_of(b):
    return to_minutes(b["start"], MONDAY) // DAY


class ArrangeTest(unittest.TestCase):
    def fresh(self, extra=(), now=BEFORE_WEEK):
        blocks = new_week(WEEK, TEMPLATE)["blocks"] + list(extra)
        return arrange(blocks, TEMPLATE, MONDAY, now)

    def test_fresh_week_places_every_goal(self):
        blocks = self.fresh()
        flexible = [b for b in blocks if b["type"] == "flexible"]
        self.assertEqual(len(flexible), sum(g["count"] for g in TEMPLATE["goals"]))
        self.assertTrue(all(b["start"] for b in flexible))

    def test_flexible_never_overlaps_anything(self):
        lecture = make_block("Lecture", "lecture", "suggested", "2026-10-06T08:00", 240)
        lecture["travelBefore"] = lecture["travelAfter"] = 30
        blocks = self.fresh([lecture])
        busy = [b for b in blocks if b["start"] and not b["skipped"]]
        for f in placed(blocks):
            for other in busy:
                if other is f:
                    continue
                a, b = span(f), span(other)
                self.assertFalse(a[0] < b[1] and b[0] < a[1], f"{f['title']} overlaps {other['title']}")

    def test_fixed_and_protected_untouched(self):
        fixed = make_block("Exam", "other", "fixed", "2026-10-07T09:00", 180)
        before = new_week(WEEK, TEMPLATE)["blocks"] + [fixed]
        after = arrange(before, TEMPLATE, MONDAY, BEFORE_WEEK)
        keep = {b["id"]: b["start"] for b in before if b["type"] != "flexible"}
        self.assertEqual(keep, {b["id"]: b["start"] for b in after if b["type"] != "flexible"})

    def test_study_weekdays_once_per_day(self):
        days = [day_of(b) for b in placed(self.fresh(), "study")]
        self.assertEqual(sorted(days), [0, 1, 2, 3, 4])

    def test_light_day_only_light_goals(self):
        light_ok = {g["category"] for g in TEMPLATE["goals"] if g.get("lightOk")}
        for b in placed(self.fresh()):
            if day_of(b) == TEMPLATE["lightDay"]:
                self.assertIn(b["category"], light_ok)

    def test_one_session_per_category_per_day_and_conflicts(self):
        blocks = [b for b in placed(self.fresh()) if not b.get("partOf")]
        seen = set()
        for b in blocks:
            key = (b["category"], day_of(b))
            self.assertNotIn(key, seen)
            seen.add(key)
        run_days = {day_of(b) for b in blocks if b["category"] == "run"}
        gym_days = {day_of(b) for b in blocks if b["category"] == "gym"}
        self.assertFalse(run_days & gym_days)

    def test_inside_placement_window(self):
        for b in placed(self.fresh()):
            lo, hi = span(b)
            day = lo // DAY
            self.assertGreaterEqual(lo % DAY, 8 * 60 + 30)
            self.assertLessEqual(hi - day * DAY, 21 * 60)

    def test_rearrange_is_stable(self):
        once = self.fresh()
        twice = arrange(once, TEMPLATE, MONDAY, BEFORE_WEEK)
        self.assertEqual(once, twice)

    def test_only_conflicting_blocks_move(self):
        once = self.fresh()
        victim = placed(once)[0]
        surprise = make_block("Surprise", "other", "fixed", victim["start"], victim["minutes"])
        after = arrange(once + [surprise], TEMPLATE, MONDAY, BEFORE_WEEK)
        moved = [b for b, a in zip(once, after) if b["start"] != a["start"]]
        self.assertEqual([b["id"] for b in moved], [victim["id"]])
        self.assertTrue(all(b["start"] for b in placed(after)))

    def test_does_not_place_in_the_past(self):
        now = datetime(2026, 10, 7, 12, 10)
        blocks = self.fresh(now=now)
        cutoff = to_minutes("2026-10-07T12:30", MONDAY)
        for b in placed(blocks):
            self.assertGreaterEqual(span(b)[0], cutoff)

    def test_unplaceable_goals_stay_in_tray(self):
        wall = [make_block("Busy", "other", "fixed", f"2026-10-{5 + d:02d}T07:00", 17 * 60) for d in range(7)]
        blocks = self.fresh(wall)
        self.assertEqual(placed(blocks), [])

    def test_preferred_window_is_respected_when_there_is_room(self):
        for b in placed(self.fresh(), "study"):
            start = to_minutes(b["start"], MONDAY) % DAY
            self.assertTrue(8 * 60 + 30 <= start and start + b["minutes"] <= 12 * 60, b["start"])

    def test_custom_window(self):
        template = {**TEMPLATE, "goals": [{**g, "prefer": "14:00-18:00"} if g["id"] == "gym" else g for g in TEMPLATE["goals"]]}
        blocks = arrange(new_week(WEEK, template)["blocks"], template, MONDAY, BEFORE_WEEK)
        for b in placed(blocks, "gym"):
            self.assertGreaterEqual(to_minutes(b["start"], MONDAY) % DAY, 14 * 60)

    def test_daily_cap(self):
        template = {**TEMPLATE, "dailyCapMinutes": 240}
        blocks = arrange(new_week(WEEK, template)["blocks"], template, MONDAY, BEFORE_WEEK)
        for day in range(7):
            self.assertLessEqual(sum(b["minutes"] for b in placed(blocks) if day_of(b) == day), 240)
        self.assertTrue(any(not b["start"] for b in blocks if b["type"] == "flexible"))

    def test_replan_moves_flexible_but_not_past_ones(self):
        now = datetime(2026, 10, 7, 12, 0)
        blocks = self.fresh(now=BEFORE_WEEK)
        badly = [{**b, "start": None} if b["type"] == "flexible" and b["start"] > "2026-10-07T12:00" else b for b in blocks]
        squeezed = arrange(badly + [make_block("Trip", "other", "fixed", "2026-10-08T08:00", 600)], TEMPLATE, MONDAY, now)
        replanned = arrange(squeezed, TEMPLATE, MONDAY, now, replan=True)
        past = lambda bs: {b["id"]: b["start"] for b in bs if b["type"] == "flexible" and b["start"] and b["start"] < "2026-10-07T12:00"}
        self.assertEqual(past(squeezed), past(replanned))
        self.assertGreaterEqual(len(placed(replanned)), len(placed(squeezed)))

    def test_low_priority_is_left_out_first(self):
        template = {**TEMPLATE, "dailyCapMinutes": 180,
                    "goals": [{**g, "priority": 3 if g["id"] == "study" else 1} for g in TEMPLATE["goals"]]}
        blocks = arrange(new_week(WEEK, template)["blocks"], template, MONDAY, BEFORE_WEEK)
        left = {b["goal"] for b in blocks if b["type"] == "flexible" and not b["start"]}
        self.assertIn("study", left)
        high_left = sum(1 for b in blocks if b["type"] == "flexible" and not b["start"] and b["goal"] != "study")
        study_placed = len(placed(blocks, "study"))
        self.assertTrue(high_left == 0 or study_placed == 0, (high_left, study_placed))

    def project(self, place_end, fit="flex", nudge=0):
        goal = {"id": "project", "title": "Project", "category": "hobby", "count": 1, "minutes": 240, "days": [0],
                "prefer": "any", "fit": fit}
        lunch = {**TEMPLATE["protected"][0], "nudge": nudge}
        template = {**TEMPLATE, "placeEnd": place_end, "goals": [goal], "protected": [lunch]}
        return template, arrange(new_week(WEEK, template)["blocks"], template, MONDAY, BEFORE_WEEK)

    def test_split_around_lunch(self):
        _, blocks = self.project("15:00")
        parts = placed(blocks)
        self.assertEqual(len(parts), 2)
        self.assertEqual(sum(b["minutes"] for b in parts), 240)
        self.assertEqual({day_of(b) for b in parts}, {0})
        self.assertEqual(sum(1 for b in parts if b.get("partOf")), 1)

    def test_shorten_when_split_does_not_fit(self):
        _, blocks = self.project("11:30")
        [b] = placed(blocks)
        self.assertEqual((b["minutes"], b["fullMinutes"]), (180, 240))

    def test_no_split_when_turned_off(self):
        _, blocks = self.project("15:00", fit="whole")
        self.assertEqual(placed(blocks), [])

    def test_only_shorten_never_splits(self):
        _, blocks = self.project("15:00", fit="shorten")
        [b] = placed(blocks)
        self.assertEqual((b["minutes"], b["fullMinutes"]), (210, 240))

    def test_lunch_moves_a_little_so_session_stays_whole(self):
        _, blocks = self.project("15:00", nudge=60)
        [b] = placed(blocks)
        self.assertEqual(b["minutes"], 240)
        lunch = next(x for x in blocks if x["title"] == "Lunch" and x["start"].startswith("2026-10-05"))
        self.assertEqual(lunch["movedFrom"], "2026-10-05T12:00")
        moved = abs(to_minutes(lunch["start"], MONDAY) - to_minutes(lunch["movedFrom"], MONDAY))
        self.assertLessEqual(moved, 60)

    def test_replan_puts_meals_back(self):
        template, blocks = self.project("15:00", nudge=60)
        wide = {**template, "placeEnd": "21:00"}
        replanned = arrange(blocks, wide, MONDAY, BEFORE_WEEK, replan=True)
        lunch = next(x for x in replanned if x["title"] == "Lunch" and x["start"].startswith("2026-10-05"))
        self.assertEqual(lunch["start"], "2026-10-05T12:00")

    def test_needless_shortening_is_undone(self):
        _, blocks = self.project("21:00")
        b = next(x for x in blocks if x["type"] == "flexible")
        b.update(start="2026-10-05T19:00", minutes=120, fullMinutes=240)
        template = {**TEMPLATE, "goals": [{"id": "project", "title": "Project", "category": "hobby", "count": 1,
                                           "minutes": 240, "days": [0], "prefer": "any"}]}
        [after] = placed(arrange(blocks, template, MONDAY, BEFORE_WEEK))
        self.assertEqual(after["minutes"], 240)
        self.assertNotIn("fullMinutes", after)

    def test_packs_tight_after_a_block(self):
        goal = {"id": "s", "title": "Study", "category": "study", "count": 1, "minutes": 165, "days": [0], "prefer": "any"}
        scrum = make_block("Scrum", "other", "fixed", "2026-10-05T08:30", 30)
        template = {**TEMPLATE, "goals": [goal], "protected": [TEMPLATE["protected"][0]], "placeEnd": "12:00"}
        [b] = placed(arrange(new_week(WEEK, template)["blocks"] + [scrum], template, MONDAY, BEFORE_WEEK))
        self.assertEqual((b["start"], b["minutes"]), ("2026-10-05T09:15", 165))

    def test_replan_joins_parts_again(self):
        template, blocks = self.project("15:00")
        wide = {**template, "placeEnd": "21:00"}
        [b] = placed(arrange(blocks, wide, MONDAY, BEFORE_WEEK, replan=True))
        self.assertEqual(b["minutes"], 240)
        self.assertNotIn("fullMinutes", b)

    def test_high_priority_shortened_beats_low_priority_whole(self):
        goals = [{"id": "project", "title": "Project", "category": "hobby", "count": 1, "minutes": 240, "days": [0],
                  "prefer": "any", "priority": 1},
                 {"id": "hw", "title": "Hobby", "category": "run", "count": 1, "minutes": 180, "days": [0],
                  "prefer": "any", "priority": 3}]
        template = {**TEMPLATE, "goals": goals, "dailyCapMinutes": 210, "conflicts": [],
                    "protected": [{**TEMPLATE["protected"][0], "nudge": 0}]}
        blocks = arrange(new_week(WEEK, template)["blocks"], template, MONDAY, BEFORE_WEEK)
        project = next(b for b in blocks if b.get("goal") == "project")
        hobby = next(b for b in blocks if b.get("goal") == "hw")
        self.assertIsNotNone(project["start"])
        self.assertIsNone(hobby["start"])

    def test_blocks_marked_free_time_do_not_use_the_cap(self):
        goal = {"id": "s", "title": "Study", "category": "study", "count": 1, "minutes": 120, "days": [0], "prefer": "any"}
        template = {**TEMPLATE, "goals": [goal], "dailyCapMinutes": 180}
        party = make_block("Birthday", "other", "fixed", "2026-10-05T08:30", 180)
        blocked = arrange(new_week(WEEK, template)["blocks"] + [party], template, MONDAY, BEFORE_WEEK)
        self.assertEqual(placed(blocked), [])
        party["noCap"] = True
        free = arrange(new_week(WEEK, template)["blocks"] + [party], template, MONDAY, BEFORE_WEEK)
        self.assertEqual(len(placed(free)), 1)

    def test_past_week_is_left_alone(self):
        blocks = new_week(WEEK, TEMPLATE)["blocks"]
        self.assertEqual(arrange(blocks, TEMPLATE, MONDAY, datetime(2026, 12, 1)), blocks)


if __name__ == "__main__":
    unittest.main()
