"""Record the demo video straight from the running site.

No slides, no mockups: the browser drives the real deployment, Playwright records
what happens, and ffmpeg adds the captions afterwards.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / "private" / "press"
SITE = sys.argv[1] if len(sys.argv) > 1 else "https://polyjury.vercel.app/"
SIZE = {"width": 1280, "height": 720}


def glide(page, to: int, steps: int = 26, pause: int = 90) -> None:
    """Scroll like a person reading, not like a script jumping."""
    start = page.evaluate("window.scrollY")
    for i in range(1, steps + 1):
        page.evaluate(f"window.scrollTo(0, {start + (to - start) * i / steps})")
        page.wait_for_timeout(pause)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    raw = OUT / "raw"
    if raw.exists():
        shutil.rmtree(raw, ignore_errors=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport=SIZE, record_video_dir=str(raw),
                                      record_video_size=SIZE, device_scale_factor=1)
        page = context.new_page()
        page.goto(SITE, wait_until="networkidle")
        page.wait_for_timeout(2200)

        # the idle workbench: left rail, modes, court status
        page.wait_for_timeout(1800)

        # open a finished case and let it play out
        page.click('button[data-mode="recorded"]')
        page.wait_for_timeout(1500)
        page.click("#sources-toggle")
        page.wait_for_timeout(2500)

        glide(page, 500)
        page.wait_for_timeout(2600)          # the jury bench filling in
        glide(page, 1150)
        page.wait_for_timeout(2400)

        # a confirmed claim, opened to show the run and the script
        for summary in page.query_selector_all("details summary")[:2]:
            summary.click()
            page.wait_for_timeout(1500)
        page.wait_for_timeout(2200)

        glide(page, 2100)
        page.wait_for_timeout(2600)
        glide(page, 3200)
        page.wait_for_timeout(2600)

        # the verdict and the prompt you paste back
        glide(page, page.evaluate("document.body.scrollHeight"))
        page.wait_for_timeout(3200)

        video = page.video.path()
        context.close()
        browser.close()

    made = Path(video)
    target = OUT / "demo-raw.webm"
    shutil.move(str(made), target)
    shutil.rmtree(raw, ignore_errors=True)
    print(f"recorded {target} ({target.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
