from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TZ = ZoneInfo("Europe/Stockholm")


def _escape(text):
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _unescape(text):
    return text.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def _fold(line):
    data = line.encode()
    parts = []
    while len(data) > 75:
        cut = 75
        while data[cut] & 0xC0 == 0x80:
            cut -= 1
        parts.append(data[:cut].decode())
        data = b" " + data[cut:]
    parts.append(data.decode())
    return "\r\n".join(parts)


def _utc(local):
    return local.replace(tzinfo=TZ).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build(blocks, name="Calm Week"):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//calm-week//EN", "CALSCALE:GREGORIAN",
             f"X-WR-CALNAME:{name}", "X-WR-TIMEZONE:Europe/Stockholm"]
    for b in blocks:
        start = datetime.fromisoformat(b["start"])
        end = start + timedelta(minutes=b["minutes"])
        lines += ["BEGIN:VEVENT", f'UID:{b["id"]}@calm-week', f"DTSTAMP:{stamp}",
                  f"DTSTART:{_utc(start)}", f"DTEND:{_utc(end)}", f'SUMMARY:{_escape(b["title"])}']
        travel = [f"{b[k]} min travel {label}" for k, label in (("travelBefore", "before"), ("travelAfter", "after")) if b.get(k)]
        if travel:
            lines.append(f'DESCRIPTION:{_escape(", ".join(travel))}')
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def _parse_time(value, params):
    if "VALUE=DATE" in params or len(value) == 8:
        return None
    if value.endswith("Z"):
        dt = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    else:
        dt = datetime.strptime(value, "%Y%m%dT%H%M%S")
        tzid = next((p[5:] for p in params if p.startswith("TZID=")), None)
        if tzid is None:
            return dt
        try:
            dt = dt.replace(tzinfo=ZoneInfo(tzid.strip('"')))
        except ZoneInfoNotFoundError:
            return dt
    return dt.astimezone(TZ).replace(tzinfo=None)


def parse(text):
    lines = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)

    events, current = [], None
    for line in lines:
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT":
            if current and "DTSTART" in current and "DTEND" in current:
                start = _parse_time(*current["DTSTART"])
                end = _parse_time(*current["DTEND"])
                if start and end and end > start:
                    events.append({
                        "uid": current.get("UID", ("", []))[0],
                        "title": _unescape(current.get("SUMMARY", ("Lecture", []))[0]) or "Lecture",
                        "start": start.strftime("%Y-%m-%dT%H:%M"),
                        "minutes": int((end - start).total_seconds() // 60),
                    })
            current = None
        elif current is not None and ":" in line:
            key, value = line.split(":", 1)
            name, *params = key.split(";")
            current[name.upper()] = (value, params)
    return events
