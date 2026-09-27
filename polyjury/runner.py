"""Where a proof script actually runs.

A claim is only reported as real if a script reproduces it. Running model-written
code is exactly the thing you should not do on your own machine, which is why the
real backend is Nebius Token Factory Sandboxes (microVM isolation, disposable).
LocalRunner exists so the pipeline can be developed before beta access is granted.
"""
from __future__ import annotations

import ast
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

VERDICT_YES = "VERDICT: REPRODUCED"
VERDICT_NO = "VERDICT: NOT_REPRODUCED"
VERDICT_UNSURE = "VERDICT: INCONCLUSIVE"
RUN_TIMEOUT = 90
BARE = re.compile(r"^(?:[A-Z ]+:\s*)?(NOT_REPRODUCED|REPRODUCED|INCONCLUSIVE)\b")
INSTALL_TIMEOUT = 60
MAX_DEPS = 40
_VER = r"[<>=!~]=?\s*[A-Za-z0-9.*+!_-]+"
_REQ_OK = re.compile(rf"^[A-Za-z0-9][A-Za-z0-9._-]*\s*(\[[A-Za-z0-9,._\s-]+\])?\s*({_VER}(\s*,\s*{_VER})*)?\s*(;[^@]*)?$")


def declared_deps(root: Path) -> list[str]:
    """What the repository says it needs, from pyproject.toml or requirements.txt.

    A clean VM has none of it, and a proof that dies on `import typer` proves
    nothing. Only plain requirement strings are kept: no -r, -e, URLs or paths,
    so a repository cannot point pip at something of its own choosing."""
    deps: list[str] = []
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8", errors="replace"))
            project = data.get("project") or {}
            deps += list(project.get("dependencies") or [])
            # the environment the repository's own tests run in: code often imports
            # what only arrives transitively there (fastapi-cli imports pydantic)
            test_names = ("test", "tests", "testing")
            for groups in (data.get("dependency-groups") or {}, project.get("optional-dependencies") or {}):
                for name in test_names:
                    deps += [d for d in groups.get(name) or [] if isinstance(d, str)]
        except (tomllib.TOMLDecodeError, TypeError):
            pass
    for name in ("requirements.txt", "requirements/base.txt", "requirements/prod.txt"):
        req = root / name
        if req.is_file():
            deps += [ln.split("#", 1)[0].strip() for ln in req.read_text(encoding="utf-8", errors="replace").splitlines()]
    seen, clean = set(), []
    for dep in deps:
        dep = dep.strip()
        if dep and dep not in seen and _REQ_OK.match(dep):
            seen.add(dep)
            clean.append(dep)
    return clean[:MAX_DEPS]


# Import name -> PyPI package, for folders that declare nothing. A fixed list, so the
# code under review can never choose what gets installed.
KNOWN_PACKAGES = {
    "PIL": "Pillow", "numpy": "numpy", "requests": "requests", "yaml": "PyYAML",
    "cv2": "opencv-python-headless", "bs4": "beautifulsoup4", "dotenv": "python-dotenv",
    "pandas": "pandas", "flask": "flask", "fastapi": "fastapi", "pydantic": "pydantic",
    "httpx": "httpx", "jinja2": "jinja2", "click": "click", "typer": "typer", "rich": "rich",
    "tqdm": "tqdm", "matplotlib": "matplotlib", "scipy": "scipy", "sklearn": "scikit-learn",
    "pydub": "pydub", "moviepy": "moviepy", "openai": "openai", "aiohttp": "aiohttp",
    "starlette": "starlette", "sqlalchemy": "sqlalchemy", "markdown": "markdown",
    "dateutil": "python-dateutil", "pytz": "pytz", "websockets": "websockets",
}


def inferred_deps(root: Path, files: list[Path]) -> list[str]:
    """Packages the code imports, limited to KNOWN_PACKAGES."""
    found: set[str] = set()
    for rel in files:
        if Path(rel).suffix != ".py":
            continue
        try:
            tree = ast.parse((root / rel).read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, OSError, ValueError):
            continue
        for node in ast.walk(tree):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else                 [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module else []
            found.update(KNOWN_PACKAGES[n.split(".")[0]] for n in names if n.split(".")[0] in KNOWN_PACKAGES)
    return sorted(found)


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
    lines = [ln.strip() for ln in (stdout or "").splitlines() if ln.strip()]
    for line in reversed(lines):
        for marker, name in verdicts.items():
            if marker in line:
                return RunResult(name, tail, runner)
    # scripts often drop the prefix: accept a bare verdict word on one of the last lines
    for line in reversed(lines[-3:]):
        m = BARE.search(line)
        if m:
            return RunResult({"NOT_REPRODUCED": "NOT_REPRODUCED", "REPRODUCED": "REPRODUCED"}.get(
                m.group(1), "UNVERIFIED"), tail, runner)
    err = (stderr or "").strip()[-1200:]
    return RunResult("UNVERIFIED", (tail + "\n" + err).strip() or "no output", runner)


class LocalRunner:
    """Subprocess on this machine. Only for code you already trust."""

    name = "local"

    def __init__(self, repo_root: Path):
        self.root = Path(repo_root)

    def run(self, script: str, overrides: dict[str, bytes] | None = None) -> RunResult:
        """overrides: {repo-relative path: new content}, for re-running a proof on a patch."""
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
            for rel, data in (overrides or {}).items():
                (work / rel).parent.mkdir(parents=True, exist_ok=True)
                (work / rel).write_bytes(data)
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

    def __init__(self, repo_root: Path, files: list[Path], image: str = "python:3.12-slim",
                 top: Path | None = None):
        from contree_sdk import ContreeSync  # imported lazily: beta access required

        self.root = Path(repo_root)
        self.files = files
        self.image_tag = image
        self.client = ContreeSync()
        self.image = self.client.images.use(image)
        # a sub-folder usually has no manifest of its own: fall back to the repo's
        self.deps = (declared_deps(self.root) or (declared_deps(Path(top)) if top else [])
                     or inferred_deps(self.root, files))
        from polyjury import robot, tools
        self.robot = robot.packages(self.root, files)
        self.deps = list(dict.fromkeys(self.deps + self.robot))
        self.apt = tools.packages(self.root, files)
        self.fonts = tools.font_names(self.root, files) if "fonts-nanum" in self.apt else []
        # images.use() makes no API call, so prove access before we promise anything.
        self.image.run("true", timeout=30, disposable=True).wait()

    def _command(self) -> str:
        """Install what the repository declares, then run the proof. A failed install
        is reported but does not stop the run: the proof may not need that package."""
        run = "exec python proof.py"
        from polyjury import tools
        steps = [tools.apt_step(self.apt)] if self.apt else []
        if self.fonts:
            steps.append(tools.font_step(self.fonts))
        if not self.deps:
            return "; ".join(steps + [run])
        pip = ("timeout %d pip install -q --disable-pip-version-check --no-input "
               "--root-user-action=ignore %s > /tmp/pip.log 2>&1"
               % (self._install_timeout(), " ".join(shlex.quote(d) for d in self.deps)))
        pip = f"{pip} || {{ echo '[polyjury] installing the declared dependencies failed:'; tail -n 4 /tmp/pip.log; }}"
        return "; ".join(steps + [pip, run])

    def _install_timeout(self) -> int:
        from polyjury import robot
        return robot.INSTALL_TIMEOUT if self.robot else INSTALL_TIMEOUT

    def _remote_path(self) -> str:
        """The VM is Linux whatever the host is: build POSIX paths, but look for
        src/ app/ lib/ in the local copy, since that is what gets uploaded."""
        parts = ["/work"] + [f"/work/{d}" for d in ("src", "app", "lib") if (self.root / d).is_dir()]
        return ":".join(parts)

    def _payload(self, script: str, overrides: dict[str, bytes] | None = None) -> dict[str, Path | bytes]:
        payload: dict[str, Path | bytes] = {"/work/proof.py": script.encode("utf-8")}
        for rel in self.files:
            payload[f"/work/{rel.as_posix()}"] = self.root / rel
        for rel, data in (overrides or {}).items():
            payload[f"/work/{Path(rel).as_posix()}"] = data
        if self.robot:
            from polyjury import robot
            payload[robot.REMOTE_HELPER] = robot.helper_source()
        return payload

    def run(self, script: str, overrides: dict[str, bytes] | None = None) -> RunResult:
        if not script.strip():
            return RunResult("UNVERIFIED", "no proof script was written", self.name)
        try:
            result = self.image.run("sh", args=["-c", self._command()], cwd="/work",
                                    env={"PYTHONPATH": self._remote_path(),
                                         "PYTHONIOENCODING": "utf-8"},
                                    files=self._payload(script, overrides), timeout=RUN_TIMEOUT + self._install_timeout() + 90,
                                    disposable=True).wait()
        except Exception as exc:  # noqa: BLE001
            return RunResult("UNVERIFIED", f"sandbox error: {type(exc).__name__}: {exc}"[:500], self.name)
        return _read_verdict(result.stdout or "", result.stderr or "", self.name)


def pick(repo_root: Path, files: list[Path], allow_local: bool = False, top: Path | None = None):
    """Sandbox when available, local only when the user explicitly allows it."""
    try:
        return SandboxRunner(repo_root, files, top=top)
    except Exception as exc:  # noqa: BLE001
        # never on the public server, whatever the flag says: there, the host is ours
        if os.environ.get("VERCEL"):
            allow_local = False
        if not allow_local:
            raise RuntimeError(
                "This claim was not tested. Polyjury only runs proofs inside Nebius Token "
                "Factory Sandboxes, and that access is not available right now "
                f"({type(exc).__name__}). The proof script below is what would decide it.") from exc
        print(f"[runner] sandbox unavailable ({type(exc).__name__}), falling back to local", flush=True)
        return LocalRunner(repo_root)
