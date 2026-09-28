"""End-to-end cross-verification: panel review -> Nemotron chair -> proof by execution."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from polyjury import collect, known, panel, pipeline, report  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "scratch" / "polyjury"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="public GitHub repo URL or a local directory")
    ap.add_argument("--allow-local-exec", action="store_true",
                    help="run proof scripts on this machine when Sandboxes is unavailable")
    ap.add_argument("--models", nargs="*", default=None)
    args = ap.parse_args()
    if args.allow_local_exec:
        os.environ["POLYJURY_ALLOW_LOCAL_EXEC"] = "1"

    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    repo = pipeline.get_repo(args.target, bucket=time.strftime("%Y%m%d-%H%M%S"))
    bundle = repo.bundle()
    print(f"[collect] {repo.name}: {len(repo.files)} files, {len(bundle)} chars", flush=True)

    reviews = panel.review(bundle, args.models)
    stats = panel.summarise(reviews)
    for m, s in stats["per_model"].items():
        print(f"[panel] {m}: {s['findings']} findings in {s['seconds']}s"
              f"{' (repaired)' if s['repaired'] else ''}{' ERROR ' + s['error'] if s['error'] else ''}", flush=True)
    findings = panel.all_findings(reviews)
    if not findings:
        print("[panel] no usable reviews"); return

    claims, dropped = pipeline.merge(findings)
    print(f"[chair] {len(findings)} findings -> {len(claims)} claims ({len(dropped)} dropped)", flush=True)
    print(f"[proof] writing and running {len(claims)} proofs", flush=True)

    def _prove(c):
        c = pipeline.prove(c, bundle, repo)
        print(f"   {c.verdict:<16} {c.title[:70]}", flush=True)
        return c

    with ThreadPoolExecutor(max_workers=3) as pool:
        claims = list(pool.map(_prove, claims))

    reproduced = [c for c in claims if c.verdict == "REPRODUCED"]
    if reproduced and "github.com" in args.target:
        print(f"[known] is any of the {len(reproduced)} already reported upstream?", flush=True)
        for c in reproduced:
            c.known = known.check(c.__dict__, args.target).__dict__
            print(f"   {c.known['status']:<8} {c.title[:70]}", flush=True)

    md = report.text_report(repo.name, claims, stats)
    prompt = report.fix_prompt(claims)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (OUT / f"report-{stamp}.md").write_text(md + ("\n\n## Paste this back to your AI\n```\n" + prompt + "\n```\n" if prompt else ""), encoding="utf-8")
    (OUT / f"run-{stamp}.json").write_text(json.dumps(
        {"repo": repo.name, "files": [f.as_posix() for f in repo.files], "panel": stats, "dropped": dropped,
         "claims": [c.__dict__ for c in claims]}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n" + md)
    print(f"[done] {round(time.time() - t0, 1)}s -> scratch/polyjury/report-{stamp}.md")


if __name__ == "__main__":
    main()
