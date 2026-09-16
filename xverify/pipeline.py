"""One place that knows the order of the work, used by both the CLI and the web app."""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from xverify import chair, collect, panel, runner

CACHE = Path(os.environ.get("XVERIFY_CACHE", Path(tempfile.gettempdir()) / "xverify-cache"))
ALLOW_LOCAL = os.environ.get("XVERIFY_ALLOW_LOCAL_EXEC", "") == "1"


def repo_cache_dir(target: str) -> Path:
    key = hashlib.sha256(target.strip().lower().encode()).hexdigest()[:16]
    return CACHE / key


def get_repo(target: str) -> collect.Repo:
    """Download once per target, then reuse the copy on disk."""
    if "github.com" not in target:
        return collect.from_path(target)
    home = repo_cache_dir(target)
    src = home / "src"
    if src.is_dir():
        try:
            inner = next(d for d in src.iterdir() if d.is_dir())
            repo = collect.from_path(inner)
            repo.name = target.rstrip("/").split("github.com/")[-1]
            return repo
        except (StopIteration, ValueError):
            pass
    return collect.from_github(target, src)


def review_one(bundle: str, model: str) -> panel.Review:
    return panel._one(model, bundle)


def merge(findings: list[dict]) -> tuple[list[chair.Claim], list[str]]:
    return chair.merge(findings)


def prove(claim: chair.Claim, bundle: str, repo: collect.Repo) -> chair.Claim:
    """Write the proof, then run it where it is safe to run."""
    claim = chair._write_proof(claim, bundle)
    if not claim.script:
        claim.verdict, claim.runner = "UNVERIFIED", "none"
        return claim
    try:
        backend = runner.pick(repo.root, repo.files, allow_local=ALLOW_LOCAL)
    except RuntimeError as exc:
        claim.verdict, claim.evidence, claim.runner = "UNVERIFIED", str(exc), "none"
        return claim
    result = backend.run(claim.script)
    claim.verdict, claim.evidence, claim.runner = result.verdict, result.output, result.runner
    if claim.verdict == "UNVERIFIED":
        claim = chair.retry_proof(claim, bundle)
        result = backend.run(claim.script)
        claim.verdict, claim.evidence, claim.runner = result.verdict, result.output, result.runner
    return claim
