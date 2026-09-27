"""Web API for cross-verification. Each step is its own short request so the
browser can show progress and nothing has to survive between serverless calls."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from polyjury import chair, collect, panel, pipeline, report, sources  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "webui"
MAX_BUNDLE = 200_000
RATE_WINDOW = 600
# Calls per 10 minutes. One full run is 1 collect, 3 reviews, 1 merge, up to 8 proofs and
# a few source lookups. Every step that spends model or search credits is limited, not
# just the first one, or the API itself becomes a free token faucet. Per visitor so one
# person cannot lock everyone out; a site-wide ceiling protects the credits. Counters live
# in each serverless instance, so this is a brake, not an exact quota.
LIMITS = {  # kind: (per visitor, whole site)
    "collect": (6, 40), "review": (18, 120), "merge": (6, 40),
    "prove": (48, 320), "sources": (24, 120), "fix": (12, 80),
}
_rate: dict[str, list[float]] = {}

app = FastAPI(title="cross-verification")


def _visitor(request: Request) -> str:
    """Vercel overwrites x-forwarded-for with the real client address, so it cannot be spoofed
    there; x-real-ip is its single-address twin."""
    ip = request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for", "").split(",")[0]
    return ip.strip() or (request.client.host if request.client else "unknown")


def _guard(request: Request, kind: str) -> None:
    now = time.time()
    per_visitor, site = LIMITS[kind]
    keys = [(f"{kind}:{_visitor(request)}", per_visitor), (f"{kind}:*", site)]
    for key, limit in keys:
        if len([t for t in _rate.get(key, []) if now - t < RATE_WINDOW]) >= limit:
            raise HTTPException(429, "Too many runs from this demo right now. Try again in a few minutes.")
    for key, _ in keys:
        _rate[key] = [t for t in _rate.get(key, []) if now - t < RATE_WINDOW] + [now]


def _github_only(target: str) -> None:
    """The server only ever reads public GitHub code. Without this, /api/prove would accept a
    path on the server itself and upload those files to the sandbox."""
    try:
        collect.parse_github(target)
    except ValueError as exc:
        raise HTTPException(400, "Paste a public GitHub repository URL.") from exc
    if not target.strip().lower().startswith(("https://github.com/", "http://github.com/", "github.com/")):
        raise HTTPException(400, "Paste a public GitHub repository URL.")


class Target(BaseModel):
    target: str


class ReviewIn(BaseModel):
    bundle: str
    model: str


class MergeIn(BaseModel):
    findings: list[dict]


class ClaimIn(BaseModel):
    claim: dict


class ProveIn(BaseModel):
    target: str
    bundle: str
    claim: dict


@app.get("/api/models")
def models() -> dict:
    return {"reviewers": panel.REVIEWERS, "chair": "nvidia/nemotron-3-super-120b-a12b",
            "sandbox": os.environ.get("NEBIUS_PROJECT_ID", "") != ""}


@app.post("/api/collect")
def collect_repo(body: Target, request: Request) -> dict:
    _guard(request, "collect")
    _github_only(body.target)
    try:
        repo = pipeline.get_repo(body.target)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Could not read that repository: {exc}") from exc
    bundle = repo.bundle()
    return {"name": repo.name, "files": [f.as_posix() for f in repo.files], "bundle": bundle}


@app.post("/api/review")
def review(body: ReviewIn, request: Request) -> dict:
    _guard(request, "review")
    if len(body.bundle) > MAX_BUNDLE:
        raise HTTPException(400, "That repository is too large for the demo.")
    if body.model not in panel.REVIEWERS:
        raise HTTPException(400, "Unknown reviewer.")
    r = pipeline.review_one(body.bundle, body.model)
    return {"model": r.model, "findings": r.findings, "seconds": r.seconds,
            "repaired": r.repaired, "error": r.error, "stood_in_for": r.stood_in_for}


@app.post("/api/merge")
def merge(body: MergeIn, request: Request) -> dict:
    _guard(request, "merge")
    if not body.findings:
        raise HTTPException(400, "No findings to merge.")
    claims, dropped = pipeline.merge(body.findings[:24])
    return {"claims": [c.__dict__ for c in claims], "dropped": dropped}


@app.post("/api/prove")
def prove(body: ProveIn, request: Request) -> dict:
    _guard(request, "prove")
    _github_only(body.target)
    if len(body.bundle) > MAX_BUNDLE:
        raise HTTPException(400, "That repository is too large for the demo.")
    try:
        repo = pipeline.get_repo(body.target)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Could not read that repository: {exc}") from exc
    claim = chair.Claim(**{k: v for k, v in body.claim.items() if k in chair.Claim.__annotations__})
    claim = pipeline.prove(claim, body.bundle, repo)
    return claim.__dict__


@app.post("/api/sources")
def cite(body: ClaimIn, request: Request) -> dict:
    """What the literature already says about this defect, via Tavily."""
    _guard(request, "sources")
    citation = sources.cite(body.claim)
    return {"claim": citation.claim, "query": citation.query,
            "why_it_matters": citation.why_it_matters, "error": citation.error,
            "sources": [s.__dict__ for s in citation.sources]}


@app.post("/api/fix-prompt")
def fix_prompt(body: MergeIn, request: Request) -> dict:
    _guard(request, "fix")
    claims = [chair.Claim(**{k: v for k, v in c.items() if k in chair.Claim.__annotations__})
              for c in body.findings]
    return {"prompt": report.fix_prompt(claims)}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(UI / "index.html")


app.mount("/", StaticFiles(directory=UI), name="ui")
