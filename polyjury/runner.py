"""Where a proof script actually runs.

A claim is only reported as real if a script reproduces it. Running model-written
code is exactly the thing you should not do on your own machine, which is why the
real backend is Nebius Token Factory Sandboxes (microVM isolation, disposable).
LocalRunner exists so the pipeline can be developed before beta access is granted.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

VERDICT_YES = "VERDICT: REPRODUCED"
VERDICT_NO = "VERDICT: NOT_REPRODUCED"
VERDICT_UNSURE = "VERDICT: INCONCLUSIVE"
RUN_TIMEOUT = 90


def _import_roots(root: Path, sep: str) -> str:
    """Packages often live in src/ or app/, so put those on the path too."""
    parts = [str(root)]
    for extra in ("src", "app", "lib"):
        if (root / extra).is_dir():
            parts.append(str(root / extra))
    return sep.join(parts)


@dataclass
class RunResult:
    verdict: str        # REPRODUCED | NOT_REPRODUCED | UNVERIFIED
    output: str
    runner: str


def _read_verdict(stdout: str, stderr: str, runner: str) -> RunResult:
    tail = (stdout or "")[-4000:]
    verdicts = {VERDICT_YES: "REPRODUCED", VERDICT_NO: "NOT_REPRODUCED", VERDICT_UNSURE: "UNVERIFIED"}
    for line in reversed((stdout or "").splitlines()):
        for marker, name in verdicts.items():
            if marker in line:
                return RunResult(name, tail, runner)
    err = (stderr or "").strip()[-1200:]
    return RunResult("UNVERIFIED", (tail + "\n" + err).strip() or "no output", runner)


class LocalRunner:
    """Subprocess on this machine. Only for code you already trust."""

    name = "local"

    def __init__(self, repo_root: Path):
        self.root = Path(repo_root)

    def run(self, script: str) -> RunResult:
        if not script.strip():
            return RunResult("UNVERIFIED", "no proof script was written", self.name)
        # Proof scripts write files and plant modules, so each one gets a throwaway copy of
        # the repository - otherwise the next review reads the previous attack. Cleanup is
        # best-effort: on Windows a file the script left open must not fail the whole run.
        tmp = Path(tempfile.mkdtemp(prefix="polyjury-"))
        try:
            work = tmp / "repo"
            shutil.copytree(self.root, work, ignore=shutil.ignore_patterns(".git", "__pycache__"),
                            dirs_exist_ok=True)
            path = tmp / "proof.py"
            path.write_text(script, encoding="utf-8")
            env = {k: v for k, v in os.environ.items()
                   if k in {"PATH", "SYSTEMROOT", "TEMP", "TMP", "LANG"}}
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONPATH"] = _import_roots(work, os.pathsep)
            try:
                proc = subprocess.run([sys.executable, "-s", "-X", "utf8", str(path)],
                                      cwd=work, env=env, capture_output=True,
                                      text=True, encoding="utf-8", errors="replace",
                                      timeout=RUN_TIMEOUT)
            except subprocess.TimeoutExpired:
                return RunResult("UNVERIFIED", f"proof script timed out after {RUN_TIMEOUT}s", self.name)
            return _read_verdict(proc.stdout, proc.stderr, self.name)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class SandboxRunner:
    """Nebius Token Factory Sandboxes: one disposable microVM per proof."""

    name = "nebius-sandbox"

    def __init__(self, repo_root: Path, files: list[Path], image: str = "python:3.12-slim"):
        from contree_sdk import ContreeSync  # imported lazily: beta access required

        self.root = Path(repo_root)
        self.files = files
        self.image_tag = image
        self.client = ContreeSync()
        self.image = self.client.images.use(image)
        # images.use() makes no API call, so prove access before we promise anything.
        self.image.run("true", timeout=30, disposable=True).wait()

    def _payload(self, script: str) -> dict[str, Path | bytes]:
        payload: dict[str, Path | bytes] = {"/work/proof.py": script.encode("utf-8")}
        for rel in self.files:
            payload[f"/work/{rel.as_posix()}"] = self.root / rel
        return payload

    def run(self, script: str) -> RunResult:
        if not script.strip():
            return RunResult("UNVERIFIED", "no proof script was written", self.name)
        try:
            result = self.image.run("python", args=["proof.py"], cwd="/work",
                                    env={"PYTHONPATH": _import_roots(Path("/work"), ":"),
                                         "PYTHONIOENCODING": "utf-8"},
                                    files=self._payload(script), timeout=RUN_TIMEOUT,
                                    disposable=True).wait()
        except Exception as exc:  # noqa: BLE001
            return RunResult("UNVERIFIED", f"sandbox error: {type(exc).__name__}: {exc}"[:500], self.name)
        return _read_verdict(result.stdout or "", result.stderr or "", self.name)


def pick(repo_root: Path, files: list[Path], allow_local: bool = False):
    """Sandbox when available, local only when the user explicitly allows it."""
    try:
        return SandboxRunner(repo_root, files)
    except Exception as exc:  # noqa: BLE001
        if not allow_local:
            raise RuntimeError(
                "This claim was not tested. Polyjury only runs proofs inside Nebius Token "
                "Factory Sandboxes, and that access is not available right now "
                f"({type(exc).__name__}). The proof script below is what would decide it.") from exc
        print(f"[runner] sandbox unavailable ({type(exc).__name__}), falling back to local", flush=True)
        return LocalRunner(repo_root)
