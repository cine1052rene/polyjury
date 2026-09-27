"""Fetch one folder of a public GitHub repository, code files only.

A zipball is the whole repository: a YouTube pipeline that commits its renders
can be half a gigabyte, most of it video. When the user points at a folder we
list the tree once and download just the source files and the dependency
manifests, which is usually well under a megabyte.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath

MAX_DOWNLOADS = 80
MANIFESTS = {"pyproject.toml", "requirements.txt", "requirements/base.txt", "requirements/prod.txt"}


def _get(url: str, timeout: int = 30) -> bytes:
    headers = {"User-Agent": "polyjury", "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN", "")
    if token and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout).read()


def _tree(owner: str, name: str, refs: tuple[str, ...]) -> tuple[str, list[dict]]:
    last: Exception | None = None
    for ref in refs:
        try:
            data = json.loads(_get(f"https://api.github.com/repos/{owner}/{name}/git/trees/{ref}?recursive=1"))
            return ref, data.get("tree") or []
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code == 403:
                raise ValueError("GitHub is rate-limiting this server right now; try again in a few minutes") from exc
    raise ValueError(f"could not list {owner}/{name}: {last!r}")


def fetch(owner: str, name: str, branch: str | None, sub: str, dest: Path) -> None:
    """Mirror the code under `sub` into dest/<name>-<ref>/, the layout a zipball has."""
    from polyjury.collect import HOT, MAX_DATA_FILES, MAX_FILE_BYTES, _is_code, is_data  # circular at import time

    ref, tree = _tree(owner, name, (branch,) if branch else ("main", "master"))
    prefix = sub.rstrip("/") + "/"
    blobs = [t for t in tree if t.get("type") == "blob"]
    if not any(t["path"].startswith(prefix) for t in blobs):
        raise ValueError(f"no folder '{sub}' in {owner}/{name}")

    ranked = []
    for t in blobs:
        path, size = t["path"], t.get("size") or 0
        if not path.startswith(prefix) or not 0 < size <= MAX_FILE_BYTES * 4:
            continue
        rel = PurePosixPath(path[len(prefix):])
        if _is_code(Path(rel)):
            ranked.append((0 if HOT.search(rel.as_posix()) else 1, -size, path))
    ranked.sort()
    wanted = [p for _, _, p in ranked[:MAX_DOWNLOADS]]
    # small inputs the scripts read; collect.locate() makes the final selection
    data = sorted((len(PurePosixPath(t["path"]).parts), t.get("size") or 0, t["path"]) for t in blobs
                  if t["path"].startswith(prefix)
                  and is_data(Path(t["path"][len(prefix):]), t.get("size") or 0))
    wanted += [p for _, _, p in data[:MAX_DATA_FILES * 2]]
    # dependency manifests, in the folder and at the top of the repository
    for t in blobs:
        rel_top, rel_sub = t["path"], t["path"][len(prefix):] if t["path"].startswith(prefix) else None
        if rel_top in MANIFESTS or (rel_sub in MANIFESTS):
            wanted.append(t["path"])
    if not ranked:
        raise ValueError(f"'{sub}' has no source files Polyjury can read")

    base = dest / f"{name}-{ref}"

    def download(path: str) -> None:
        blob = _get(f"https://raw.githubusercontent.com/{owner}/{name}/{ref}/{path}")
        target = base / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(download, dict.fromkeys(wanted)))
