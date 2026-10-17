"""Record a short tour of the live site as it is now (for demo video v6).

No jury is convened, so no model credits are spent: the tour opens the site, replays the
Recorded verdict (a finished case, at reading speed), opens the bring-your-own-key form and the
sign-in policy page. Writes private/press/tour-raw.webm and tour-events.json (seconds from start).
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

PRESS = Path(__file__).resolve().parents[1] / "private" / "press"
SITE = "https://polyjury.vercel.app"
SIZE = {"width": 1280, "height": 720}


def main() -> None:
    raw = PRESS / "tour-raw"
    shutil.rmtree(raw, ignore_errors=True)
    events: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport=SIZE, record_video_dir=str(raw), record_video_size=SIZE,
                                      device_scale_factor=1)
        page = context.new_page()
        t0 = time.time()

        def mark(name: str) -> None:
            events.append({"event": name, "t": round(time.time() - t0, 2)})
            print(f"{events[-1]['t']:6.2f}  {name}", flush=True)

        page.goto(SITE, wait_until="networkidle")
        page.wait_for_selector("#signin:not([hidden])", timeout=15000)
        mark("home")
        page.wait_for_timeout(2500)
        page.click('button[data-mode="recorded"]')
        mark("recorded")
        page.wait_for_selector(".verdict-line", timeout=30000)
        mark("replayed")
        page.wait_for_timeout(1500)
        page.mouse.wheel(0, -4000)
        page.wait_for_timeout(600)
        page.click("#byok-open")
        mark("byok")
        page.wait_for_timeout(2500)
        page.goto(SITE + "/privacy.html", wait_until="networkidle")
        mark("policy")
        page.wait_for_timeout(2500)
        page.mouse.wheel(0, 520)
        page.wait_for_timeout(2500)
        mark("end")
        video = page.video
        context.close()
        browser.close()
        shutil.move(video.path(), PRESS / "tour-raw.webm")
    shutil.rmtree(raw, ignore_errors=True)
    (PRESS / "tour-events.json").write_text(json.dumps(events, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
