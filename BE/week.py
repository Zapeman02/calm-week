import hashlib
import uuid
from datetime import date, datetime, time, timedelta

DAY = 1440


def hm(text):
    h, m = text.split(":")
    return int(h) * 60 + int(m)


def monday_of(week_id):
    year, week = week_id.split("-W")
    return date.fromisocalendar(int(year), int(week), 1)


def week_id_of(day):
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def to_minutes(start, monday):
    dt = datetime.fromisoformat(start)
    return (dt.date() - monday).days * DAY + dt.hour * 60 + dt.minute


def from_minutes(minutes, monday):
    return (datetime.combine(monday, time()) + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M")


def make_block(title, category, kind, start, minutes, goal=None, block_id=None):
    return {
        "id": block_id or uuid.uuid4().hex[:8],
        "title": title,
        "category": category,
        "type": kind,
        "start": start,
        "minutes": minutes,
        "travelBefore": 0,
        "travelAfter": 0,
        "skipped": False,
        "goal": goal,
    }


def goal_block(goal):
    block = make_block(goal["title"], goal["category"], "flexible", None, goal["minutes"], goal=goal["id"])
    block.update(travelBefore=goal.get("travelBefore", 0), travelAfter=goal.get("travelAfter", 0))
    if goal.get("noCap"):
        block["noCap"] = True
    return block


def new_week(week_id, template):
    monday = monday_of(week_id)
    blocks = []
    for p in template["protected"]:
        for d in p["days"]:
            start = from_minutes(d * DAY + hm(p["start"]), monday)
            blocks.append(make_block(p["title"], p["category"], "protected", start, p["minutes"]))
    for g in template["goals"]:
        for _ in range(g["count"]):
            blocks.append(goal_block(g))
    return {"blocks": blocks}


def merge_suggested(blocks, events, monday):
    """Replace this week's imported lectures, keeping skip and travel choices."""
    old = {b["id"]: b for b in blocks if b["type"] == "suggested"}
    merged = [b for b in blocks if b["type"] != "suggested"]
    seen = set()
    for e in events:
        # TimeEdit lists a lecture once per student group, so the same slot can appear twice.
        if (e["title"], e["start"], e["minutes"]) in seen:
            continue
        seen.add((e["title"], e["start"], e["minutes"]))
        offset = to_minutes(e["start"], monday)
        if not 0 <= offset < 7 * DAY:
            continue
        block_id = "te-" + hashlib.sha1(f'{e["uid"]}|{e["start"]}'.encode()).hexdigest()[:10]
        block = make_block(e["title"], "lecture", "suggested", e["start"], e["minutes"], block_id=block_id)
        if block_id in old:
            for key in ("skipped", "travelBefore", "travelAfter"):
                block[key] = old[block_id][key]
        merged.append(block)
    return merged


def sync_goals(blocks, goals, now):
    """Reset: sessions from now on match the goal list exactly. Earlier sessions and fixed ones stay and count."""
    wanted = {g["id"]: g for g in goals}
    past = lambda b: b["start"] is not None and b["start"] < now
    blocks = join_parts(blocks, now)
    kept, counts = [], {}
    for b in sorted(blocks, key=lambda b: (not past(b) and b["type"] == "flexible", b["start"] is None, b["start"] or "")):
        goal = b.get("goal")
        if not goal or b.get("partOf") or b["type"] not in ("flexible", "fixed"):
            kept.append(b)
            continue
        if b["type"] == "flexible" and not past(b):
            if goal not in wanted or counts.get(goal, 0) >= wanted[goal]["count"]:
                continue
            g = wanted[goal]
            b = {k: v for k, v in b.items() if k != "noCap"}
            b.update(title=g["title"], category=g["category"], minutes=g["minutes"], travelBefore=g.get("travelBefore", 0),
                     travelAfter=g.get("travelAfter", 0), **({"noCap": True} if g.get("noCap") else {}))
        counts[goal] = counts.get(goal, 0) + 1
        kept.append(b)
    for g in goals:
        for _ in range(g["count"] - counts.get(g["id"], 0)):
            kept.append(goal_block(g))
    return kept


def apply_goal_changes(blocks, old_goals, new_goals):
    """Save: only what changed in settings touches the week. Placed sessions keep time and length."""
    old = {g["id"]: g for g in old_goals}
    new = {g["id"]: g for g in new_goals}
    result, dropped = [], {}
    for b in reversed(blocks):
        goal = b.get("goal")
        if goal in old and b["type"] == "flexible" and not b["start"] and not b.get("partOf"):
            surplus = old[goal]["count"] - new[goal]["count"] if goal in new else len(blocks)
            if dropped.get(goal, 0) < surplus:
                dropped[goal] = dropped.get(goal, 0) + 1
                continue
        if goal in new and goal in old:
            g = new[goal]
            b = {k: v for k, v in b.items() if k != "noCap"}
            b.update(title=g["title"], category=g["category"], **({"noCap": True} if g.get("noCap") else {}))
            if not b["start"]:
                b.update(minutes=g["minutes"], travelBefore=g.get("travelBefore", 0), travelAfter=g.get("travelAfter", 0))
        result.append(b)
    result.reverse()
    for g in new_goals:
        for _ in range(g["count"] - old[g["id"]]["count"] if g["id"] in old else g["count"]):
            result.append(goal_block(g))
    return result


def sync_protected(blocks, old, new, now):
    """Move meals and free time from now on to the new default, unless that day was moved by hand."""
    result = []
    for b in blocks:
        for o, n in zip(old, new):
            if b["type"] == "protected" and b["title"] == o["title"] and b["start"] and b["start"] >= now \
                    and b["start"][11:] == o["start"] and b["minutes"] == o["minutes"]:
                b = {**b, "start": b["start"][:11] + n["start"], "minutes": n["minutes"]}
        result.append(b)
    return result



def join_parts(blocks, cutoff=None):
    """Undo splitting, shortening and meal nudges for blocks that are unplaced or start at/after cutoff."""
    is_open = lambda b: b["start"] is None or (cutoff is not None and b["start"] >= cutoff)
    result = []
    for b in blocks:
        if b["type"] == "protected" and "movedFrom" in b and cutoff is not None and b["movedFrom"] >= cutoff:
            b = {**{k: v for k, v in b.items() if k != "movedFrom"}, "start": b["movedFrom"]}
        if b["type"] == "flexible" and is_open(b):
            if b.get("partOf"):
                continue
            if "fullMinutes" in b:
                b = {**{k: v for k, v in b.items() if k != "fullMinutes"}, "minutes": b["fullMinutes"]}
        result.append(b)
    return result


def reset_protected(blocks, protected, now):
    """Every meal and free time block from now on goes back to its default time and length."""
    defaults = {p["title"]: p for p in protected}
    result = []
    for b in blocks:
        p = defaults.get(b["title"])
        if b["type"] == "protected" and p and b["start"] and b["start"] >= now:
            b = {**b, "start": b["start"][:11] + p["start"], "minutes": p["minutes"]}
        result.append(b)
    return result
