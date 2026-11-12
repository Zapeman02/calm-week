import unittest

import ics
from week import make_block, merge_suggested, monday_of

TIMEEDIT_SAMPLE = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:abc-1
DTSTART:20261006T060000Z
DTEND:20261006T080000Z
SUMMARY:Embedded systems\\, lecture
END:VEVENT
BEGIN:VEVENT
UID:abc-2
DTSTART;TZID=Europe/Stockholm:20261008T131500
DTEND;TZID=Europe/Stockholm:20261008T150000
SUMMARY:Lab
 oratory
END:VEVENT
BEGIN:VEVENT
UID:abc-3
DTSTART;VALUE=DATE:20261009
DTEND;VALUE=DATE:20261010
SUMMARY:All day
END:VEVENT
END:VCALENDAR
"""


class IcsTest(unittest.TestCase):
    def test_parse_timeedit(self):
        events = ics.parse(TIMEEDIT_SAMPLE)
        self.assertEqual([e["title"] for e in events], ["Embedded systems, lecture", "Laboratory"])
        self.assertEqual(events[0]["start"], "2026-10-06T08:00")
        self.assertEqual(events[0]["minutes"], 120)
        self.assertEqual(events[1]["start"], "2026-10-08T13:15")
        self.assertEqual(events[1]["minutes"], 105)

    def test_round_trip(self):
        long_title = "Study; signals, systems and a very long title that needs folding åäö " * 2
        block = make_block(long_title, "study", "flexible", "2026-10-07T09:30", 90)
        text = ics.build([block])
        self.assertTrue(all(len(line.encode()) <= 75 for line in text.split("\r\n")))
        [event] = ics.parse(text)
        self.assertEqual(event["title"], long_title)
        self.assertEqual(event["start"], "2026-10-07T09:30")
        self.assertEqual(event["minutes"], 90)
        self.assertEqual(event["uid"], f'{block["id"]}@calm-week')

    def test_merge_keeps_skip_choice(self):
        monday = monday_of("2026-W41")
        events = ics.parse(TIMEEDIT_SAMPLE)
        first = merge_suggested([], events, monday)
        self.assertEqual(len(first), 2)
        first[0]["skipped"] = True
        again = merge_suggested(first, events, monday)
        self.assertTrue(again[0]["skipped"])
        self.assertEqual(merge_suggested([], events, monday_of("2026-W42")), [])


if __name__ == "__main__":
    unittest.main()
