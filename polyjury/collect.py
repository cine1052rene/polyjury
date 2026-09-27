"""Collect reviewable source files from a public GitHub repo or a local path."""
from __future__ import annotations

import io
import re
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

CODE_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rb", ".php", ".java", ".rs"}
CONFIG_EXT = {".json", ".yaml", ".yml", ".toml", ".env", ".cfg"}
SKIP_DIR = {"node_modules", ".git", "dist", "build", "out", "vendor", "__pycache__", ".next",
            "venv", ".venv", "site-packages", "migrations", "test", "tests", "__tests__"}
SKIP_NAME = re.compile(r"(\.min\.|lock|\.map$|package-lock|yarn\.lock|poetry\.lock)", re.I)
# Files most likely to hold the defects that hurt a published app.
HOT = re.compile(r"(main|app|server|index|api|route|auth|login|admin|payment|upload|db|model|handler|middleware)", re.I)

# Small data files the code reads (scripts, subtitles, configs). They are uploaded to the
# sandbox so a proof can run the real code on the real inputs; reviewers only see their names.
DATA_EXT = {".json", ".txt", ".csv", ".tsv", ".yaml", ".yml", ".toml", ".ini", ".srt", ".vtt", ".md", ".xml"}
SECRET = re.compile(r"(^\.env|secret|token|credential|password|passwd|private|apikey|api_key|\.pem$|\.key$|id_rsa)", re.I)
MAX_DATA_FILES = 40
MAX_DATA_BYTES = 32_000
MAX_DATA_TOTAL = 400_000

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
    top: Path | None = None    # repository top when root is a sub-folder of it
    data: list[Path] = field(default_factory=list)  # inputs and unreviewed sources, sandbox only

    def bundle(self, budget: int = MAX_TOTAL_BYTES) -> str:
        """One text blob the reviewers read, with clear file markers."""
        out, used = [], 0
        from polyjury import tools
        note = tools.bundle_note(self.root, self.files + self.data)
        note += tools.font_note(tools.font_names(self.root, self.files + self.data))
        if note:
            out.append(note)
        if self.data:
            names = ", ".join(rel.as_posix() for rel in self.data)
            out.append(f"### ALSO PRESENT when the proof runs (data files and other source files, not shown here): {names}\n")
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


def is_data(rel: Path, size: int) -> bool:
    """A small, non-secret input file the code is likely to read."""
    if any(part in SKIP_DIR or part.startswith(".") for part in rel.parts[:-1]):
        return False
    if SKIP_NAME.search(rel.name) or SECRET.search(rel.name) or rel.name == "package-lock.json":
        return False
    return rel.suffix.lower() in DATA_EXT and 0 < size <= MAX_DATA_BYTES


def _pick_data(root: Path) -> list[Path]:
    cands = []
    for p in root.rglob("*"):
        if p.is_file():
            rel = p.relative_to(root)
            size = p.stat().st_size
            if is_data(rel, size):
                cands.append((len(rel.parts), size, rel))
    cands.sort()  # shallow and small first: configs next to the scripts that read them
    picked, total = [], 0
    for _, size, rel in cands:
        if len(picked) >= MAX_DATA_FILES or total + size > MAX_DATA_TOTAL:
            break
        picked.append(rel)
        total += size
    return picked


def _pick_support(root: Path, picked: list[Path]) -> list[Path]:
    """Source files the reviewers did not get, so a proof can still import or run them."""
    chosen, out, total = set(picked), [], 0
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if not p.is_file() or rel in chosen or not _is_code(rel):
            continue
        size = p.stat().st_size
        if 0 < size <= MAX_FILE_BYTES * 4 and len(out) < 60 and total + size <= 1_000_000:
            out.append(rel)
            total += size
    return out


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
    return Repo(name=root.name, root=root, files=files, total_bytes=total, data=_pick_data(root) + _pick_support(root, files))


GITHUB = re.compile(
    r"github\.com/([^/\s]+)/([^/#?\s]+?)(?:\.git)?(?:/tree/([^/#?\s]+)((?:/[^#?\s]*)?))?/?(?:[#?].*)?$", re.I)


def parse_github(url: str) -> tuple[str, str, str | None, str]:
    """owner, repo, branch (None = try main then master), sub-folder ('' = whole repo).

    Accepts what the browser shows when you open a folder on GitHub:
    github.com/owner/repo/tree/main/shorts/gomgom"""
    m = GITHUB.search(url.strip())
    if not m:
        raise ValueError(f"not a GitHub repo URL: {url}")
    owner, name, branch, sub = m.group(1), m.group(2), m.group(3), (m.group(4) or "")
    parts = [p for p in sub.strip("/").split("/") if p]
    if any(p in ("..", ".") for p in parts):
        raise ValueError("that folder path is not allowed")
    return owner, name, branch, "/".join(parts)


def locate(src: Path, url: str) -> Repo:
    """The downloaded copy under src, narrowed to the requested folder."""
    owner, name, _, sub = parse_github(url)
    inner = next(d for d in src.iterdir() if d.is_dir())
    root = (inner / sub).resolve() if sub else inner
    if sub and (inner.resolve() not in root.parents or not root.is_dir()):
        raise ValueError(f"no folder '{sub}' in {owner}/{name}")
    repo = from_path(root)
    repo.name = f"{owner}/{name}" + (f"/{sub}" if sub else "")
    repo.top = inner if sub else None
    return repo


def from_github(url: str, dest: Path) -> Repo:
    """Download a public repo zipball (no token, no git needed)."""
    owner, name, branch, sub = parse_github(url)
    dest.mkdir(parents=True, exist_ok=True)
    if sub:  # one folder: fetch its code, not the whole repository
        from polyjury import github_folder
        github_folder.fetch(owner, name, branch, sub, dest)
        return locate(dest, url)
    last = None
    for ref in ((branch,) if branch else ("main", "master")):
        api = f"https://codeload.github.com/{owner}/{name}/zip/refs/heads/{ref}"
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
    return locate(dest, url)


def load(target: str, workdir: Path) -> Repo:
    """Accept either a GitHub URL or a local directory."""
    if "github.com" in target:
        return from_github(target, workdir / "src")
    return from_path(target)
