"""Record a real verdict on the live site — and keep it.

One run produces both artefacts, so they can never disagree:
  private/press/live-raw.webm      the screen, for the demo video
  private/press/live-events.json   when each stage happened, for the captions
  webui/example.json               the same verdict, for the "Recorded verdict" mode

Nothing is mocked. The browser types a repository into the deployed site, the
jurors and Nemotron run on Nebius Token Factory, the proofs run in Sandboxes.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "private" / "press"
SITE = "https://polyjury.vercel.app/"
ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
REPO = ARGS[0] if ARGS else "https://github.com/tiangolo/fastapi-cli"
NAME = sys.argv[sys.argv.index("--name") + 1] if "--name" in sys.argv else "live"  # output file prefix
WRITE_EXAMPLE = "--no-example" not in sys.argv
SIZE = {"width": 1280, "height": 720}
LIMIT = 420  # seconds; a verdict normally takes two to three minutes


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    raw = OUT / "raw-live"
    shutil.rmtree(raw, ignore_errors=True)
    events: list[dict] = []
    calls: dict[str, list] = {"collect": [], "review": [], "merge": [], "prove": [], "fix-prompt": []}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport=SIZE, record_video_dir=str(raw),
                                      record_video_size=SIZE, device_scale_factor=1)
        page = context.new_page()
        t0 = time.time()

        def mark(name: str, **extra) -> None:
            events.append({"t": round(time.time() - t0, 2), "event": name, **extra})
            print(f"{events[-1]['t']:7.1f}s  {name} {extra or ''}", flush=True)

        def on_response(resp) -> None:
            path = resp.url.split("polyjury.vercel.app", 1)[-1]
            if not path.startswith("/api/") or resp.request.method != "POST":
                return
            key = path[len("/api/"):]
            if key not in calls:
                return
            try:
                body, sent = resp.json(), json.loads(resp.request.post_data or "{}")
            except Exception:  # noqa: BLE001
                return
            calls[key].append({"sent": sent, "got": body})
            extra = {"model": sent.get("model")} if key == "review" else {}
            if key == "prove":
                extra = {"verdict": body.get("verdict"), "runner": body.get("runner")}
            mark(f"api:{key}", status=resp.status, **extra)

        page.on("response", on_response)
        page.goto(SITE, wait_until="networkidle")
        page.wait_for_selector("#sandbox-state:not(:text('checking'))")
        mark("loaded")
        page.wait_for_timeout(2500)

        page.click("#sources-toggle")
        page.wait_for_timeout(1200)
        page.click("#target")
        page.type("#target", REPO, delay=45)
        page.wait_for_timeout(700)
        mark("submit")
        page.click("#run-btn")

        # follow the newest step, the way a person watching would
        last_steps, seen_done = 0, False
        while time.time() - t0 < LIMIT:
            page.wait_for_timeout(400)
            steps = page.eval_on_selector_all(".step", "els => els.length")
            if steps != last_steps:
                last_steps = steps
                mark("step", n=steps)
                page.evaluate("""() => { const s = [...document.querySelectorAll('.step')].pop();
                    window.scrollTo({top: s.getBoundingClientRect().top + scrollY - 90, behavior: 'smooth'}); }""")
            if page.is_visible("#error"):
                mark("error", text=page.inner_text("#error"))
                break
            if page.query_selector(".copy") and not seen_done:
                seen_done = True
                mark("verdict")
                break

        if seen_done:
            page.wait_for_timeout(1200)
            # the claims, then open the first confirmed one to show the run and the script
            page.evaluate("""() => { const c = document.querySelector('.claims');
                window.scrollTo({top: c.getBoundingClientRect().top + scrollY - 90, behavior: 'smooth'}); }""")
            page.wait_for_timeout(3000)
            mark("open-proof")
            opened = page.query_selector_all(".claim.reproduced details summary")[:2]
            for summary in opened:
                summary.click()
                page.wait_for_timeout(1800)
            if opened:
                opened[0].evaluate("el => window.scrollTo({top: el.getBoundingClientRect().top + scrollY - 140, behavior: 'smooth'})")
            page.wait_for_timeout(5000)
            # a claim the audit threw out: the run contradicted its own verdict
            audited = page.evaluate("""() => { const d = [...document.querySelectorAll('.claim details')]
                .find(x => x.querySelector('pre') && x.querySelector('pre').textContent.includes('marked unverified'));
                if (!d) return false; d.open = true;
                window.scrollTo({top: d.getBoundingClientRect().top + scrollY - 140, behavior: 'smooth'}); return true; }""")
            if audited:
                mark("open-audit")
                page.wait_for_timeout(6000)
            mark("final")
            page.evaluate("window.scrollTo({top: document.body.scrollHeight, behavior: 'smooth'})")
            page.wait_for_timeout(5000)
            mark("end")

        video = page.video.path()
        context.close()
        browser.close()

    target = OUT / f"{NAME}-raw.webm"
    shutil.move(str(video), target)
    shutil.rmtree(raw, ignore_errors=True)
    (OUT / f"{NAME}-events.json").write_text(json.dumps(events, indent=2), encoding="utf-8")
    (OUT / f"{NAME}-calls.json").write_text(json.dumps(calls, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"recorded {target} ({target.stat().st_size // 1024} KB)")
    if seen_done and WRITE_EXAMPLE:
        write_example(calls)


def write_example(calls: dict) -> None:
    """The same run, in the shape the "Recorded verdict" mode replays."""
    collect = calls["collect"][0]["got"]
    reviews = [{"model": c["sent"]["model"], **{k: c["got"].get(k) for k in ("seconds", "repaired", "error", "findings")}}
               for c in calls["review"]]
    merge = calls["merge"][0]["got"]
    order = [c.get("title") for c in merge["claims"]]
    proved = {c["got"].get("title"): c["got"] for c in calls["prove"]}
    claims = [proved.get(t, c) for t, c in zip(order, merge["claims"])]
    example = {
        "repo": {"name": collect["name"], "files": collect["files"]},
        "reviewers": [r["model"] for r in reviews],
        "reviews": reviews,
        "findings_total": sum(len(r["findings"] or []) for r in reviews),
        "dropped": len(merge.get("dropped") or []),
        "claims": claims,
        "fix_prompt": (calls["fix-prompt"][0]["got"].get("prompt") if calls["fix-prompt"] else ""),
    }
    path = ROOT / "webui" / "example.json"
    path.write_text(json.dumps(example, ensure_ascii=False, indent=1), encoding="utf-8")
    runners = sorted({c.get("runner") for c in claims})
    print(f"example.json: {len(claims)} claims, runners={runners}")


if __name__ == "__main__":
    main()
