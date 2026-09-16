"""Collect reviewable source files from a public GitHub repo or a local path."""
from __future__ import annotations

import io
import re
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

CODE_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rb", ".php", ".java", ".rs"}
CONFIG_EXT = {".json", ".yaml", ".yml", ".toml", ".env", ".cfg"}
SKIP_DIR = {"node_modules", ".git", "dist", "build", "vendor", "__pycache__", ".next",
            "venv", ".venv", "site-packages", "migrations", "test", "tests", "__tests__"}
SKIP_NAME = re.compile(r"(\.min\.|lock|\.map$|package-lock|yarn\.lock|poetry\.lock)", re.I)
# Files most likely to hold the defects that hurt a published app.
HOT = re.compile(r"(main|app|server|index|api|route|auth|login|admin|payment|upload|db|model|handler|middleware)", re.I)

MAX_FILES = 24
MAX_FILE_BYTES = 40_000
MAX_TOTAL_BYTES = 130_000


@dataclass
class Repo:
    """A checked-out copy of the code under review."""
    name: str
    root: Path
    files: list[Path]          # paths relative to root
    total_bytes: int

    def bundle(self, budget: int = MAX_TOTAL_BYTES) -> str:
        """One text blob the reviewers read, with clear file markers."""
        out, used = [], 0
        for rel in self.files:
            text = (self.root / rel).read_text(encoding="utf-8", errors="replace")[:MAX_FILE_BYTES]
            block = f"### FILE: {rel.as_posix()}\n{text}\n"
            if used + len(block) > budget:
                break
            out.append(block)
            used += len(block)
        return "\n".join(out)


def _is_code(rel: Path) -> bool:
    if any(part in SKIP_DIR for part in rel.parts[:-1]):
        return False
    if SKIP_NAME.search(rel.name):
        return False
    return rel.suffix.lower() in CODE_EXT or rel.name in {"Dockerfile", "vercel.json"}


def _pick(root: Path) -> tuple[list[Path], int]:
    """Rank candidate files: hot names first, then bigger files."""
    cands = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if not _is_code(rel):
            continue
        try:
            size = p.stat().st_size
        except OSError:
            continue
        if size == 0 or size > MAX_FILE_BYTES * 4:
            continue
        cands.append((0 if HOT.search(rel.as_posix()) else 1, -size, rel))
    cands.sort()
    picked = [rel for _, _, rel in cands[:MAX_FILES]]
    total = sum((root / rel).stat().st_size for rel in picked)
    return picked, total


def from_path(path: str | Path) -> Repo:
    root = Path(path).resolve()
    if not root.is_dir():
        raise ValueError(f"not a directory: {root}")
    files, total = _pick(root)
    if not files:
        raise ValueError("no reviewable source files found")
    return Repo(name=root.name, root=root, files=files, total_bytes=total)


GITHUB = re.compile(r"github\.com/([^/]+)/([^/#?]+?)(?:\.git)?/?$", re.I)


def from_github(url: str, dest: Path) -> Repo:
    """Download a public repo zipball (no token, no git needed)."""
    m = GITHUB.search(url.strip())
    if not m:
        raise ValueError(f"not a GitHub repo URL: {url}")
    owner, name = m.group(1), m.group(2)
    dest.mkdir(parents=True, exist_ok=True)
    last = None
    for branch in ("main", "master"):
        api = f"https://codeload.github.com/{owner}/{name}/zip/refs/heads/{branch}"
        try:
            req = urllib.request.Request(api, headers={"User-Agent": "polyjury"})
            blob = urllib.request.urlopen(req, timeout=60).read()
            break
        except Exception as exc:  # noqa: BLE001
            last = exc
    else:
        raise ValueError(f"could not download {owner}/{name}: {last!r}")
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        zf.extractall(dest)
    inner = next(d for d in dest.iterdir() if d.is_dir())
    repo = from_path(inner)
    repo.name = f"{owner}/{name}"
    return repo


def load(target: str, workdir: Path) -> Repo:
    """Accept either a GitHub URL or a local directory."""
    if "github.com" in target:
        return from_github(target, workdir / "src")
    return from_path(target)
