import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import date, timedelta
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PORT = 8799
BASE = f"http://localhost:{PORT}"
SHOTS = ROOT / "e2e" / "screenshots"
FUTURE = date.today() + timedelta(days=21)
WEEK = "{}-W{:02d}".format(*FUTURE.isocalendar()[:2])


def api_week():
    with urlopen(f"{BASE}/api/week/{WEEK}") as res:
        return json.load(res)


class UiBase:
    browser_name = None

    @classmethod
    def setUpClass(cls):
        cls.data = tempfile.TemporaryDirectory()
        Path(cls.data.name, "config.json").write_text(json.dumps({"sync": False}))
        shutil.copy(ROOT / "BE" / "tests" / "template.json", Path(cls.data.name, "template.json"))
        env = {**os.environ, "CALM_DATA": cls.data.name, "CALM_PORT": str(PORT)}
        cls.server = subprocess.Popen([sys.executable, str(ROOT / "BE" / "server.py")], env=env, stdout=subprocess.DEVNULL)
        for _ in range(50):
            try:
                urlopen(f"{BASE}/api/heartbeat")
                break
            except OSError:
                time.sleep(0.1)
        cls.pw = sync_playwright().start()
        cls.browser = getattr(cls.pw, cls.browser_name).launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.terminate()
        cls.server.wait()
        cls.data.cleanup()

    def setUp(self):
        self.page = self.browser.new_page(viewport={"width": 1440, "height": 900})
        self.page.goto(f"{BASE}/?week={WEEK}")
        self.page.wait_for_selector(".block")

    def tearDown(self):
        self.page.close()

    def flexible_node(self):
        b = next(b for b in api_week()["blocks"] if b["type"] == "flexible" and b["start"])
        return b, self.page.locator(f'.block[data-id="{b["id"]}"] .body')

    def drag_by(self, locator, dx, dy):
        box = locator.bounding_box()
        x, y = box["x"] + box["width"] / 2, box["y"] + 10
        self.page.mouse.move(x, y)
        self.page.mouse.down()
        self.page.mouse.move(x + dx / 2, y + dy / 2, steps=5)
        self.page.mouse.move(x + dx, y + dy, steps=5)
        self.page.mouse.up()
        self.page.wait_for_timeout(300)

    def test_renders_week(self):
        self.assertEqual(self.page.locator(".day-col").count(), 7)
        self.assertIn("goals placed", self.page.locator("#status").inner_text())
        self.assertIn("free time protected", self.page.locator("#status").inner_text())
        SHOTS.mkdir(exist_ok=True)
        self.page.screenshot(path=str(SHOTS / f"week-{self.browser_name}.png"))

    def test_drag_moves_block_and_undo_restores(self):
        block, node = self.flexible_node()
        ppm = float(self.page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--ppm')").replace("px", ""))
        self.drag_by(node, 0, 60 * ppm)
        moved = next(b for b in api_week()["blocks"] if b["id"] == block["id"])
        self.assertNotEqual(moved["start"], block["start"])
        self.page.click("#undo")
        self.page.wait_for_timeout(300)
        restored = next(b for b in api_week()["blocks"] if b["id"] == block["id"])
        self.assertEqual(restored["start"], block["start"])

    def test_create_fixed_block_then_rearrange_has_no_overlap(self):
        block, node = self.flexible_node()
        box = node.bounding_box()
        days = self.page.locator("#days").bounding_box()
        col = days["width"] / 7
        x = days["x"] + (int((box["x"] - days["x"]) / col) + 0.5) * col
        self.page.mouse.move(x, days["y"] + 4)
        self.page.mouse.down()
        self.page.mouse.move(x, days["y"] + box["height"], steps=8)
        self.page.mouse.up()
        self.page.locator(".popover input").fill("Dentist")
        self.page.keyboard.press("Enter")
        self.page.click("[data-close]")
        dentist_node = self.page.locator(".block.type-fixed .body", has_text="Dentist")
        self.drag_by(dentist_node, 0, box["y"] - dentist_node.bounding_box()["y"])
        self.page.click("#arrange")
        self.page.wait_for_timeout(500)
        blocks = api_week()["blocks"]
        dentist = next(b for b in blocks if b["title"] == "Dentist")
        self.assertEqual(dentist["type"], "fixed")
        moved = next(b for b in blocks if b["id"] == block["id"])
        self.assertNotEqual(moved["start"], block["start"])
        self.page.screenshot(path=str(SHOTS / f"rearranged-{self.browser_name}.png"))

    def test_popover_changes_travel(self):
        block, node = self.flexible_node()
        node.click()
        self.page.click('[data-step="travelBefore"][data-d="1"]')
        self.page.wait_for_timeout(300)
        updated = next(b for b in api_week()["blocks"] if b["id"] == block["id"])
        self.assertEqual(updated["travelBefore"], 15)

    def test_settings_add_activity_fills_tray(self):
        self.page.click("#settings-open")
        self.page.fill("#timeedit", "https://example.com/none.ics")
        self.page.click("#goal-add")
        self.page.locator(".goal:last-child input").fill("Walk")
        self.page.click('.goal:last-child [data-k="count"][data-d="1"]')
        self.page.screenshot(path=str(SHOTS / f"settings-{self.browser_name}.png"))
        self.page.click("#settings-form [type=submit]")
        self.page.wait_for_selector("#settings", state="hidden")
        self.assertEqual(self.page.locator(".tray-item, .block", has_text="Walk").count(), 2)
        self.page.click("#settings-open")
        self.assertEqual(self.page.input_value("#timeedit"), "https://example.com/none.ics")
        self.page.click(".goal:last-child [data-toggle]")
        self.page.select_option(".goal:last-child select", "custom")
        self.page.screenshot(path=str(SHOTS / f"settings-open-{self.browser_name}.png"))
        self.page.click(".goal:last-child [data-remove]")
        self.page.click("#settings-form [type=submit]")
        self.page.wait_for_selector("#settings", state="hidden")
        self.assertEqual(self.page.locator(".tray-item, .block", has_text="Walk").count(), 0)

    def test_claude_dialog_opens_and_closes(self):
        self.page.click("#claude-open")
        self.page.fill("#wish", "Lighter week")
        self.page.screenshot(path=str(SHOTS / f"claude-{self.browser_name}.png"))
        self.page.click("#claude-cancel")
        self.page.wait_for_selector("#claude", state="hidden")

    def test_tray_quick_delete(self):
        self.page.click("#settings-open")
        self.page.click("#goal-add")
        self.page.locator(".goal:last-child input").fill("Too much")
        for _ in range(13):
            self.page.click('.goal:last-child [data-k="count"][data-d="1"]')
        self.page.click("#settings-form [type=submit]")
        self.page.wait_for_selector("#settings", state="hidden")
        before = self.page.locator(".tray-item").count()
        self.assertGreater(before, 0)
        self.page.locator(".tray-item [data-drop]").first.click()
        self.page.wait_for_timeout(300)
        self.assertEqual(self.page.locator(".tray-item").count(), before - 1)
        self.assertEqual(sum(1 for b in api_week()["blocks"] if b["type"] == "flexible" and not b["start"]), before - 1)

    def test_mark_block_as_free_time(self):
        block, node = self.flexible_node()
        node.click()
        self.page.click('[data-nocap="1"]')
        self.page.wait_for_timeout(300)
        self.assertTrue(next(b for b in api_week()["blocks"] if b["id"] == block["id"]).get("noCap"))
        self.page.screenshot(path=str(SHOTS / f"popover-{self.browser_name}.png"))

    def test_week_switch(self):
        label = self.page.locator("#week-label").inner_text()
        self.page.click("#next")
        self.page.wait_for_function(f"document.querySelector('#week-label').innerText !== {json.dumps(label)}")
        self.page.click("#prev")
        self.page.wait_for_function(f"document.querySelector('#week-label').innerText === {json.dumps(label)}")


class ChromiumTest(UiBase, unittest.TestCase):
    browser_name = "chromium"


class WebkitTest(UiBase, unittest.TestCase):
    browser_name = "webkit"


if __name__ == "__main__":
    unittest.main()
