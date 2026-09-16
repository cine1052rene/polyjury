"""Web API for cross-verification. Each step is its own short request so the
browser can show progress and nothing has to survive between serverless calls."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from polyjury import chair, panel, pipeline, report  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "webui"
MAX_BUNDLE = 200_000
RATE_LIMIT, RATE_WINDOW = 12, 600
_rate: dict[str, list[float]] = {}

app = FastAPI(title="cross-verification")


def _guard(key: str = "demo") -> None:
    now = time.time()
    hits = [t for t in _rate.get(key, []) if now - t < RATE_WINDOW]
    if len(hits) >= RATE_LIMIT:
        raise HTTPException(429, "Too many runs from this demo right now. Try again in a few minutes.")
    hits.append(now)
    _rate[key] = hits


class Target(BaseModel):
    target: str


class ReviewIn(BaseModel):
    bundle: str
    model: str


class MergeIn(BaseModel):
    findings: list[dict]


class ProveIn(BaseModel):
    target: str
    bundle: str
    claim: dict


@app.get("/api/models")
def models() -> dict:
    return {"reviewers": panel.REVIEWERS, "chair": "nvidia/nemotron-3-super-120b-a12b",
            "sandbox": os.environ.get("NEBIUS_PROJECT_ID", "") != ""}


@app.post("/api/collect")
def collect_repo(body: Target) -> dict:
    _guard()
    if "github.com" not in body.target:
        raise HTTPException(400, "Paste a public GitHub repository URL.")
    try:
        repo = pipeline.get_repo(body.target)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Could not read that repository: {exc}") from exc
    bundle = repo.bundle()
    return {"name": repo.name, "files": [f.as_posix() for f in repo.files], "bundle": bundle}


@app.post("/api/review")
def review(body: ReviewIn) -> dict:
    if len(body.bundle) > MAX_BUNDLE:
        raise HTTPException(400, "That repository is too large for the demo.")
    if body.model not in panel.REVIEWERS:
        raise HTTPException(400, "Unknown reviewer.")
    r = pipeline.review_one(body.bundle, body.model)
    return {"model": r.model, "findings": r.findings, "seconds": r.seconds,
            "repaired": r.repaired, "error": r.error}


@app.post("/api/merge")
def merge(body: MergeIn) -> dict:
    if not body.findings:
        raise HTTPException(400, "No findings to merge.")
    claims, dropped = pipeline.merge(body.findings[:24])
    return {"claims": [c.__dict__ for c in claims], "dropped": dropped}


@app.post("/api/prove")
def prove(body: ProveIn) -> dict:
    if len(body.bundle) > MAX_BUNDLE:
        raise HTTPException(400, "That repository is too large for the demo.")
    try:
        repo = pipeline.get_repo(body.target)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Could not read that repository: {exc}") from exc
    claim = chair.Claim(**{k: v for k, v in body.claim.items() if k in chair.Claim.__annotations__})
    claim = pipeline.prove(claim, body.bundle, repo)
    return claim.__dict__


@app.post("/api/fix-prompt")
def fix_prompt(body: MergeIn) -> dict:
    claims = [chair.Claim(**{k: v for k, v in c.items() if k in chair.Claim.__annotations__})
              for c in body.findings]
    return {"prompt": report.fix_prompt(claims)}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(UI / "index.html")


app.mount("/", StaticFiles(directory=UI), name="ui")
