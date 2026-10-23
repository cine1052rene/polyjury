"""Record a finished case for the site's "Recorded verdict" mode, without a browser.

Calls the live API in the same order as webui/app.js (collect → review ×3 → merge →
prove each claim → upstream check → fix prompt → fix) and writes the responses in the
format replay() reads, plus the fix results so the replay can show step 6.

  python scripts/record_example.py https://github.com/google-deepmind/mujoco_menagerie/tree/main/robotstudio_so101 webui/example-robot.json
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = os.environ.get("POLYJURY_BASE", "https://polyjury.vercel.app")


def call(path: str, body: dict | None = None, timeout: int = 300) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method="GET" if body is None else "POST",
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode())


def safe_call(path: str, body: dict) -> dict:
    try:
        return call(path, body)
    except Exception as err:  # noqa: BLE001 — a failed step is recorded, not fatal
        detail = getattr(err, "read", lambda: b"")().decode(errors="replace")[:300]
        return {"error": f"{err} {detail}".strip()}


def main(target: str, out: Path) -> None:
    t0 = time.time()
    log = lambda msg: print(f"[{time.time() - t0:6.1f}s] {msg}", flush=True)  # noqa: E731
    reviewers = call("/api/models")["reviewers"]
    repo = call("/api/collect", {"target": target})
    log(f"collect: {repo['name']} {len(repo['files'])} files")

    with ThreadPoolExecutor(len(reviewers)) as pool:
        reviews = list(pool.map(lambda m: {"model": m, **safe_call("/api/review", {"bundle": repo["bundle"], "model": m})},
                                reviewers))
    findings = [f for r in reviews for f in r.get("findings", [])]
    log(f"review: {[len(r.get('findings', [])) for r in reviews]}")

    merged = call("/api/merge", {"findings": findings})
    claims = merged["claims"]
    log(f"merge: {len(findings)} -> {len(claims)} claims")

    def prove(c: dict) -> dict:
        got = safe_call("/api/prove", {"target": target, "bundle": repo["bundle"], "claim": c})
        return got if "verdict" in got else {**c, "verdict": "UNVERIFIED", "evidence": got.get("error", "")}

    with ThreadPoolExecutor(4) as pool:
        proved = list(pool.map(prove, claims))
    log(f"prove: {[c['verdict'] for c in proved]}")

    for c in proved:
        if c["verdict"] == "REPRODUCED":
            c["known"] = safe_call("/api/known", {"target": target, "bundle": "", "claim": c})
    prompt = safe_call("/api/fix-prompt", {"findings": proved}).get("prompt", "")

    fixable = [c for c in proved if c["verdict"] == "REPRODUCED" and c.get("seal")
               and (c.get("proof_kind") == "dynamic" or "polyjury-simulator" in (c.get("models") or []))]
    with ThreadPoolExecutor(4) as pool:
        fixes = list(pool.map(lambda c: {"title": c["title"],
                                         "result": safe_call("/api/fix", {"target": target, "bundle": repo["bundle"], "claim": c})},
                              fixable))
    log(f"fix: {[f['result'].get('fixed') for f in fixes]}")

    keep = ("title", "file", "where", "severity", "what_breaks", "models", "script", "what_it_proves",
            "proof_kind", "verdict", "evidence", "runner", "known")
    example = {
        "recorded": time.strftime("%Y-%m-%d"),
        "target": target,
        "repo": {"name": repo["name"], "files": repo["files"]},
        "reviewers": reviewers,
        "reviews": [{k: r.get(k) for k in ("model", "findings", "seconds", "repaired", "error", "stood_in_for") if k in r}
                    for r in reviews],
        "findings_total": len(findings),
        "dropped": len(merged.get("dropped", [])),
        "claims": [{k: c.get(k) for k in keep if k in c} for c in proved],
        "fix_prompt": prompt,
        "fixes": fixes,
    }
    out.write_text(json.dumps(example, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"wrote {out}")


if __name__ == "__main__":
    main(sys.argv[1], Path(sys.argv[2]))
