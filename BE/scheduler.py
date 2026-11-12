import uuid
from datetime import datetime

from week import DAY, from_minutes, hm, join_parts, to_minutes

PREFER_WINDOWS = {"morning": ("08:30", "12:00"), "afternoon": ("12:00", "17:00"), "evening": ("17:00", "21:00")}
DEFAULT_GOAL = {"days": list(range(7)), "prefer": "any", "lightOk": False, "priority": 2, "fit": "flex"}
FITS = ("flex", "shorten", "whole")
MIN_PART = 60
SNAP = 15
NUDGES = (15, -15, 30, -30, 45, -45, 60, -60)


def fit_of(goal):
    """flex = may split or shorten, shorten = never split, whole = never change. Old templates used split: bool."""
    if goal.get("fit") in FITS:
        return goal["fit"]
    return "whole" if goal.get("split") is False else "flex"
PRIORITIES = (1, 2, 3)
NO_CAP = 24 * 60


def prefer_window(prefer):
    """A preset name or a custom "HH:MM-HH:MM" range; None means any time."""
    if prefer in PREFER_WINDOWS:
        lo, hi = PREFER_WINDOWS[prefer]
    elif "-" in prefer:
        lo, hi = prefer.split("-")
    else:
        return None
    return hm(lo), hm(hi)


class Arranger:
    """Keeps flexible blocks that still fit where they are and places the rest in free slots."""

    def __init__(self, template, monday, now, order=0, tight=True, cap_slack=0):
        self.t = template
        self.nudge = {p["title"]: p.get("nudge", 0) for p in template["protected"]}
        self.monday = monday
        self.goals = {g["id"]: g for g in template["goals"]}
        self.conflicts = {frozenset(pair) for pair in template["conflicts"]}
        self.place_start = hm(template["placeStart"])
        self.place_end = hm(template["placeEnd"])
        self.slot = template["slotMinutes"]
        self.gap = template["gapMinutes"]
        self.cap = template.get("dailyCapMinutes", NO_CAP) + cap_slack
        self.earliest = self._earliest(now)
        self.order = order
        self.tight = tight
        self.occupied = []
        self.load = [0] * 7

    def _earliest(self, now):
        offset = to_minutes(now.strftime("%Y-%m-%dT%H:%M"), self.monday)
        return max(0, -(-offset // self.slot) * self.slot)

    def arrange(self, blocks, replan=False):
        result = [dict(b) for b in blocks]
        if self.earliest >= 7 * DAY:
            return result
        result = join_parts(result, from_minutes(self.earliest, self.monday) if replan else None)
        if replan:
            for b in result:
                if b["type"] == "flexible" and b["start"] and to_minutes(b["start"], self.monday) >= self.earliest:
                    b["start"] = None
        for b in result:
            if b["type"] != "flexible" and b["start"] and not b["skipped"]:
                self._occupy(b, to_minutes(b["start"], self.monday))

        placed = sorted((b for b in result if b["type"] == "flexible" and b["start"]), key=lambda b: b["start"])
        for b in placed:
            start = to_minutes(b["start"], self.monday)
            if start < self.earliest or self._fits(b, start):
                self._occupy(b, start)
            else:
                b["start"] = None

        loose = [b for b in result if b["type"] == "flexible" and not b["start"]]
        loose.sort(key=self._order)
        meals = [b for b in result if b["type"] == "protected" and self.nudge.get(b["title"]) and b["start"]
                 and to_minutes(b["start"], self.monday) >= self.earliest]
        # Each priority level gets every option (whole, meal move, split, shorten) before the next level,
        # so a shortened high priority session beats a whole low priority one.
        for priority in PRIORITIES:
            group = [b for b in loose if self._goal(b)["priority"] == priority]
            for b in group:
                best = self._best(b)
                if best is not None:
                    b["start"] = from_minutes(best, self.monday)
                    self._occupy(b, best)
            for b in group:
                if not b["start"]:
                    self._move_meal_for(b, meals)
            for b in group:
                fit = fit_of(self._goal(b))
                if b["start"] or fit == "whole":
                    continue
                part = self._split(b) if fit == "flex" else None
                if part:
                    result.append(part)
                else:
                    self._shorten(b)
        return self._make_whole(result)

    def _make_whole(self, result):
        """A split or shortened session (from Claude or an earlier plan) goes back to full length when it fits."""
        drop = set()
        for b in result:
            if b["type"] != "flexible" or "fullMinutes" not in b or not b["start"] or to_minutes(b["start"], self.monday) < self.earliest:
                continue
            parts = [b] + [x for x in result if x.get("partOf") == b["id"] and x["start"]]
            for p in parts:
                self._release(p, to_minutes(p["start"], self.monday))
            whole = {k: v for k, v in b.items() if k != "fullMinutes"}
            whole["minutes"] = b["fullMinutes"]
            whole["travelAfter"] = parts[-1]["travelAfter"]
            here = to_minutes(b["start"], self.monday)
            start = here if self._fits(whole, here) else self._best(whole)
            if start is None:
                for p in parts:
                    self._occupy(p, to_minutes(p["start"], self.monday))
                continue
            b.clear()
            b.update(whole, start=from_minutes(start, self.monday))
            self._occupy(b, start)
            drop.update(p["id"] for p in parts[1:])
        return [b for b in result if b["id"] not in drop]

    def _move_meal_for(self, block, meals):
        """Shift lunch or dinner up to an hour if that lets a whole session fit the same day."""
        days = self._goal(block)["days"]
        for meal in meals:
            here = to_minutes(meal["start"], self.monday)
            if here // DAY not in days:
                continue
            self._release(meal, here)
            for offset in NUDGES:
                there = here + offset
                if abs(offset) > self.nudge[meal["title"]] or there < self.earliest or not self._free(meal, there):
                    continue
                self._occupy(meal, there)
                start = self._best(block, [here // DAY])
                if start is not None:
                    meal.setdefault("movedFrom", meal["start"])
                    meal["start"] = from_minutes(there, self.monday)
                    block["start"] = from_minutes(start, self.monday)
                    self._occupy(block, start)
                    return True
                self._release(meal, there)
            self._occupy(meal, here)
        return False

    def _free(self, block, start):
        lo, hi = start, start + block["minutes"]
        return lo // DAY == (hi - 1) // DAY and not any(lo < ohi and olo < hi for olo, ohi, *_ in self.occupied)

    def _best(self, block, days=None):
        candidates = [s for s in self._candidates(block) if (days is None or s // DAY in days) and self._fits(block, s)]
        return min(candidates, key=lambda s: self._score(block, s)) if candidates else None

    def _split(self, block):
        """Two parts on the same day, e.g. around lunch. Returns the second part."""
        full = block["minutes"]
        first_len = full // 2 // self.slot * self.slot
        if first_len < MIN_PART or full - first_len < MIN_PART:
            return None
        first = {**block, "minutes": first_len, "travelAfter": 0}
        second = {**block, "id": uuid.uuid4().hex[:8], "minutes": full - first_len, "travelBefore": 0, "partOf": block["id"]}
        tried = set()
        while True:
            start = self._best(first, [d for d in range(7) if d not in tried])
            if start is None:
                return None
            day = start // DAY
            tried.add(day)
            self._occupy(first, start)
            second_start = self._best(second, [day])
            if second_start is not None:
                block.update(first, start=from_minutes(start, self.monday), fullMinutes=full)
                second["start"] = from_minutes(second_start, self.monday)
                self._occupy(second, second_start)
                return second
            self._release(first, start)

    def _shorten(self, block):
        full = block["minutes"]
        shortest = max(self.slot, -(-full // 2 // self.slot) * self.slot)
        for minutes in range(full - self.slot, shortest - 1, -self.slot):
            trial = {**block, "minutes": minutes}
            start = self._best(trial)
            if start is not None:
                block.update(minutes=minutes, start=from_minutes(start, self.monday), fullMinutes=full)
                self._occupy(block, start)
                return True
        return False

    def _order(self, block):
        goal = self._goal(block)
        any_time = prefer_window(goal["prefer"]) is None
        return (goal["priority"],) + [
            (-block["minutes"], len(goal["days"])),
            (any_time, -block["minutes"], len(goal["days"])),
            (len(goal["days"]), any_time, -block["minutes"]),
        ][self.order]

    def _goal(self, block):
        return {**DEFAULT_GOAL, **self.goals.get(block.get("goal"), {})}

    def _occupy(self, block, start):
        lo = start - block["travelBefore"]
        hi = start + block["minutes"] + block["travelAfter"]
        self.occupied.append((lo, hi, block["category"], start // DAY, block["type"] == "protected", self._group(block)))
        if self._counts(block) and 0 <= start < 7 * DAY:
            self.load[start // DAY] += block["minutes"]

    def _release(self, block, start):
        entry = (start - block["travelBefore"], self._group(block), block["category"])
        for i, (lo, _, cat, _, _, group) in enumerate(self.occupied):
            if (lo, group, cat) == entry:
                del self.occupied[i]
                break
        if self._counts(block) and 0 <= start < 7 * DAY:
            self.load[start // DAY] -= block["minutes"]

    @staticmethod
    def _counts(block):
        """Toward the daily cap. Meals, free time and blocks marked as free time (noCap) don't count."""
        return block["type"] != "protected" and not block.get("noCap")

    @staticmethod
    def _group(block):
        return block.get("partOf") or block["id"]

    def _candidates(self, block):
        """The slot grid plus starts that sit tight against existing blocks, so short gaps get used."""
        starts = {s for day in range(7) for s in range(day * DAY + self.place_start, day * DAY + self.place_end, self.slot)}
        for lo, hi, _, _, protected, _ in (self.occupied if self.tight else []):
            gap = 0 if protected else self.gap
            starts.add(-(-(hi + gap + block["travelBefore"]) // SNAP) * SNAP)
            starts.add((lo - gap - block["travelAfter"] - block["minutes"]) // SNAP * SNAP)
        return sorted(starts)

    def _fits(self, block, start):
        goal = self._goal(block)
        day = start // DAY
        if day not in goal["days"] or (day == self.t["lightDay"] and not goal["lightOk"]):
            return False
        lo = start - block["travelBefore"]
        hi = start + block["minutes"] + block["travelAfter"]
        if lo < max(self.earliest, day * DAY + self.place_start) or hi > day * DAY + self.place_end:
            return False
        if self.load[day] + block["minutes"] > self.cap:
            return False
        group = self._group(block)
        for olo, ohi, cat, oday, protected, ogroup in self.occupied:
            gap = 0 if protected else self.gap
            if lo < ohi + gap and olo < hi + gap:
                return False
            if oday == day and ogroup != group and (cat == block["category"] or frozenset((cat, block["category"])) in self.conflicts):
                return False
        return True

    def _score(self, block, start):
        day = start // DAY
        adjacent = any(cat == block["category"] and abs(oday - day) == 1 for _, _, cat, oday, _, _ in self.occupied)
        window = prefer_window(self._goal(block)["prefer"])
        off_preference = bool(window) and not (window[0] <= start % DAY and start % DAY + block["minutes"] <= window[1])
        return (off_preference, adjacent, self.load[day] // 60, day, start)


ORDERS = 3


def arrange(blocks, template, monday, now=None, replan=False, cap_slack=0):
    """replan=True moves every flexible session from now on; otherwise sessions that still fit stay put.
    Greedy placement depends on order, so a few orders are tried. The winner places the most high
    priority time, then normal, then low, then splits or shortens the fewest sessions."""
    now = now or datetime.now()
    arrangers = [Arranger(template, monday, now, order, tight, cap_slack) for order in range(ORDERS) for tight in (False, True)]
    results = [a.arrange(blocks, replan) for a in arrangers]

    def placed(i):
        flexible = [b for b in results[i] if b["type"] == "flexible" and b["start"]]
        by_priority = [sum(b["minutes"] for b in flexible if arrangers[i]._goal(b)["priority"] == p) for p in PRIORITIES]
        broken = sum(1 for b in flexible if b.get("partOf") or "fullMinutes" in b)
        return (*by_priority, -broken)

    return results[max(range(len(results)), key=placed)]
