"""One place that knows the order of the work, used by both the CLI and the web app."""
from __future__ import annotations

import hashlib
import os
import time
import tempfile
from pathlib import Path

from polyjury import chair, collect, panel, proofcheck, robot, runner

CACHE = Path(os.environ.get("POLYJURY_CACHE", Path(tempfile.gettempdir()) / "polyjury-cache"))



def repo_cache_dir(target: str, bucket: str = "") -> Path:
    """A fresh bucket means a fresh copy: a checkout that proofs have touched is never reused."""
    key = hashlib.sha256((target.strip().lower() + "|" + bucket).encode()).hexdigest()[:16]
    return CACHE / key


def get_repo(target: str, bucket: str = "") -> collect.Repo:
    """Download once per (target, bucket), then reuse that copy on disk."""
    if "github.com" not in target:
        return collect.from_path(target)
    home = repo_cache_dir(target, bucket or time.strftime("%Y%m%d%H"))
    src = home / "src"
    if src.is_dir():
        try:
            return collect.locate(src, target)
        except StopIteration:
            pass
    return collect.from_github(target, src)


def review_one(bundle: str, model: str) -> panel.Review:
    return panel._one_with_retry(model, bundle)


def merge(findings: list[dict]) -> tuple[list[chair.Claim], list[str]]:
    return chair.merge(findings)


def prove(claim: chair.Claim, bundle: str, repo: collect.Repo) -> chair.Claim:
    """Write the proof, then run it where it is safe to run."""
    started = time.time()
    simulated = robot.SIM_MODEL in claim.models
    if simulated:  # rebuilt here from the template: whatever script the client sent is ignored
        claim.script = robot.sim_script(repo.root, repo.files, claim.file)
        claim.proof_kind, claim.what_it_proves = "dynamic", "MuJoCo sweeps every joint alone from home; exact meshes confirm each contact"
        if not claim.script:
            claim.evidence = "that file is not a robot description in this repository"
    else:
        claim = chair._write_proof(claim, bundle)
    if not claim.script:
        claim.verdict, claim.runner = "UNVERIFIED", "none"
        return claim
    try:
        backend = runner.pick(repo.root, repo.files + repo.data, top=repo.top, allow_local=os.environ.get("POLYJURY_ALLOW_LOCAL_EXEC", "") == "1")
    except RuntimeError as exc:
        claim.verdict, claim.evidence, claim.runner = "UNVERIFIED", str(exc), "none"
        return claim
    result = backend.run(claim.script)
    claim.verdict, claim.evidence, claim.runner = result.verdict, result.output, result.runner
    # a second attempt costs another proof and another VM: skip it when the first
    # already used most of the 300 s a serverless call gets
    if claim.verdict == "UNVERIFIED" and not simulated and time.time() - started < 110:
        claim = chair.retry_proof(claim, bundle)
        result = backend.run(claim.script)
        claim.verdict, claim.evidence, claim.runner = result.verdict, result.output, result.runner
    # a script can print the defect happening and still call it NOT_REPRODUCED
    why = chair.audit(claim)
    if why:
        claim.verdict = "UNVERIFIED"
        claim.evidence = (claim.evidence.rstrip()
                          + f"\n[polyjury] marked unverified: the run contradicts its own verdict. {why}")
    # the chair's own KIND label is a claim too: a proof that never ran the repo is a reading
    if claim.proof_kind == "dynamic" and not proofcheck.runs_repo_code(claim.script, repo.files + repo.data):
        claim.proof_kind = "static"
    return claim
