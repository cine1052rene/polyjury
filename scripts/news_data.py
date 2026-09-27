"""Raw datasets behind a claim: replication files, spreadsheets, CSVs.

A document quoting a corrected figure is still someone's conclusion. When the data the figure
was computed from is public, the proof should compute it again from the rows themselves.
"""
from __future__ import annotations

import json
import re
import urllib.request
from urllib.parse import urlparse

from core.tavily_client import get_search
from polyjury.llm import chat

DATA_EXT = (".csv", ".tsv", ".xlsx", ".xls", ".dta")
MAX_FILE = 5_000_000
MAX_FILES = 4
LINK = re.compile(r"https?://[^\s)\]\"'<>]+")


def _get(url: str, limit: int = MAX_FILE) -> bytes | None:
    req = urllib.request.Request(url, headers={"user-agent": "polyjury-news-probe"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read(limit + 1)
        return body if len(body) <= limit else None
    except Exception:  # noqa: BLE001
        return None


def _repo_files(owner: str, repo: str) -> list[str]:
    """Data files at the top of a GitHub repository and one level down."""
    out, queue = [], [f"https://api.github.com/repos/{owner}/{repo}/contents"]
    for depth in range(2):
        nxt = []
        for url in queue:
            raw = _get(url, 2_000_000)
            try:
                items = json.loads(raw or b"[]")
            except ValueError:
                continue
            for it in items if isinstance(items, list) else []:
                if it.get("type") == "file" and it["name"].lower().endswith(DATA_EXT) and it.get("size", 0) <= MAX_FILE:
                    out.append(it["download_url"])
                elif it.get("type") == "dir" and depth == 0:
                    nxt.append(it["url"])
        queue = nxt[:5]
    return out


NAME_PROMPT = """Articles about a claim are below. Name the study, report or dataset its figures
come from, as a short web search phrase (authors, title, year). One line, nothing else. If no
single source is identifiable, answer NONE."""


def name_source(claim: str, docs: dict[str, bytes]) -> str:
    """Claims rarely name their source ("countries with high debt grow slower"); the articles do."""
    text = "\n\n".join(v.decode("utf-8", "replace")[:3000] for k, v in docs.items() if k.startswith("/work/sources/"))
    try:
        raw, _ = chat(NAME_PROMPT, f"CLAIM: {claim}\n\nARTICLES:\n{text[:30000]}", think=False,
                      max_tokens=80, temperature=0, timeout=60)
    except Exception:  # noqa: BLE001
        return ""
    line = (raw or "").strip().splitlines()[0].strip() if (raw or "").strip() else ""
    return "" if line.upper().startswith("NONE") else line[:160]


def candidates(claim: str, docs: dict[str, bytes]) -> tuple[list[str], str]:
    """Links to data files in the documents, plus data files in GitHub repositories found by
    searching for the named source's replication data."""
    source = name_source(claim, docs)
    print("    figures come from:", source or "(no single source named)")
    urls = []
    for body in docs.values():
        for u in LINK.findall(body.decode("utf-8", "replace")):
            if urlparse(u).path.lower().endswith(DATA_EXT):
                urls.append(u.rstrip(".,;"))
    repos = set()
    try:
        found = get_search()._client.search(query=f"{source or claim} replication data csv github",
                                            max_results=8).get("results", [])
    except Exception as exc:  # noqa: BLE001
        print("  data search failed:", exc)
        found = []
    for r in found:
        p = urlparse(r.get("url", ""))
        parts = [x for x in p.path.split("/") if x]
        if p.netloc == "github.com" and len(parts) >= 2:
            repos.add((parts[0], parts[1]))
        elif p.path.lower().endswith(DATA_EXT):
            urls.append(r["url"])
    for owner, repo in list(repos)[:4]:
        urls += _repo_files(owner, repo)
    seen = []
    for u in urls:
        if u not in seen:
            seen.append(u)
    return seen, f"{claim} {source}"


STOP = {"the", "and", "for", "with", "that", "from", "percent", "were", "was", "are", "than", "into",
        "cars", "data", "real", "world", "time", "his", "her", "up", "at", "of", "in", "to", "a", "an", "is", "on", "by", "see", "all"}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", text.lower()) if w not in STOP}


def fetch(urls: list[str], topic: str = "") -> dict[str, bytes]:
    """Download data files whose name or header shares a word with the claim and its named
    source; a search for replication data also returns unrelated popular datasets."""
    want = _words(topic)
    out = {}
    for u in urls:
        if len(out) >= MAX_FILES:
            break
        body = _get(u)
        if not body:
            continue
        head = body[:2000].decode("utf-8", "replace") if u.lower().endswith((".csv", ".tsv")) else ""
        # one shared word lets "real-world" match a world-airports dataset; ask for two
        if want and len(want & _words(u + " " + head)) < 2:
            print(f"    skipped unrelated data file: {u}")
            continue
        name = re.sub(r"[^A-Za-z0-9._-]", "_", urlparse(u).path.rsplit("/", 1)[-1])[:80] or "data"
        out[f"/work/data/{len(out)}_{name}"] = body
        print(f"    data file: {u} ({len(body):,} bytes)")
    return out


def preview(path: str, body: bytes) -> str:
    """Header and a few rows, so the chair knows what the file can compute."""
    if path.lower().endswith((".csv", ".tsv")):
        lines = body.decode("utf-8", "replace").splitlines()
        return f"=== DATA FILE {path} ({len(lines)} rows)\n" + "\n".join(lines[:6])
    return f"=== DATA FILE {path} (binary {path.rsplit('.', 1)[-1]}, {len(body):,} bytes; open with pandas)"
