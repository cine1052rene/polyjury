"""Is this defect already known upstream?

A reproduced defect is worth reporting only if nobody has. Before Polyjury tells you to open
an issue, it searches the repository's own issues and pull requests, and the wider web through
Tavily (advisories, changelogs, forks), for the same defect under the project's own vocabulary
— the part name, the file, the error. Nemotron then decides whether any hit is the same defect,
and whether it is still open or already dealt with.

Lesson this stage comes from: a Menagerie actuator range Polyjury reproduced on 2026-09-28 was
already the subject of a pull request opened the day before, and that PR also showed the
diagnosis was on the wrong side. A title-keyword search had missed it.
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from core.tavily_client import get_search
from polyjury import collect
from polyjury.llm import chat, parse_json

QUERY_PROMPT = """A defect was reproduced in the repository {repo}. Write the search queries a
maintainer would type into that repository's issue tracker to find an existing report of the
SAME defect. Use the project's own vocabulary: the component, joint, function, file or option
name; the error text. Do not use generic words such as "bug", "issue", "problem".

Answer with JSON only: {{"queries": [str, str]}} — two queries, each 2 to 5 words."""

JUDGE_PROMPT = """You decide whether a reproduced defect is already known upstream.

The defect, then a list of issues, pull requests and web pages found by searching for it.
Pick the ONE item that is about the same defect — the same file or component AND the same
failure — if any. A page about a different joint, endpoint or error is not a match, even if
the words overlap.

status:
- "known": a matching issue or pull request in this repository is still open
- "fixed": a matching issue or pull request in this repository is closed or merged
- "elsewhere": no issue or pull request here, but a web page (documentation, another
  project's tracker, an advisory) describes the same failure
- "new": nothing matches

Answer with JSON only: {"status": "known"|"fixed"|"elsewhere"|"new", "ref": int index of the
match or null, "why": str (max 30 words, name what matches or say what the closest hit was about)}"""

GITHUB_ISSUES = "https://api.github.com/search/issues"
STOP = set("the a an of in on to and or is are be can with for from by via when not no as at it its this that into".split())
_canonical: dict[str, str] = {}


def _gh_request(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "polyjury"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def canonical(owner_repo: str) -> str:
    """Search rejects a repository's old name (tiangolo/fastapi-cli -> 422); the repo endpoint
    follows the rename and gives the name the issues live under."""
    if owner_repo not in _canonical:
        try:
            _canonical[owner_repo] = _gh_request(f"https://api.github.com/repos/{owner_repo}").get("full_name") or owner_repo
        except Exception:  # noqa: BLE001
            _canonical[owner_repo] = owner_repo
    return _canonical[owner_repo]


@dataclass
class Candidate:
    kind: str        # issue | pull | page
    title: str
    url: str
    state: str = ""  # open | closed | merged | ""
    number: int = 0
    snippet: str = ""


@dataclass
class Known:
    claim: str
    status: str = "unknown"  # new | known | fixed | unknown
    ref: dict = field(default_factory=dict)
    why: str = ""
    queries: list[str] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)
    error: str = ""


def _fallback_queries(claim: dict) -> list[str]:
    stem = os.path.basename(claim.get("file", "")).rsplit(".", 1)[0]
    words = [w for w in re.findall(r"[A-Za-z_][A-Za-z_0-9\-]{2,}", claim.get("title", "")) if w.lower() not in STOP]
    idents = re.findall(r"[A-Za-z_][A-Za-z_0-9]*_[A-Za-z_0-9]+", claim.get("title", "") + " " + claim.get("where", ""))
    out = [" ".join((idents[:2] or words[:3]))]
    if stem and stem not in out[0]:
        out.append(f"{stem} {' '.join(words[:2])}".strip())
    return [q for q in out if q]


def queries_for(claim: dict, owner_repo: str) -> list[str]:
    text = (f"title: {claim.get('title', '')}\nfile: {claim.get('file', '')}\nwhere: {claim.get('where', '')}\n"
            f"what breaks: {claim.get('what_breaks', '')}\nwhat the run showed: {(claim.get('evidence') or '')[:600]}")
    try:
        raw, _ = chat(QUERY_PROMPT.format(repo=owner_repo), text[:3000], think=False, max_tokens=300,
                      temperature=0, timeout=60)
        qs = [str(q).strip() for q in (parse_json(raw) or {}).get("queries", []) if str(q).strip()]
        if qs:
            return qs[:2]
    except Exception:  # noqa: BLE001
        pass
    return _fallback_queries(claim)


def _github(owner_repo: str, query: str, limit: int = 5) -> list[Candidate]:
    """Issues and pull requests, open and closed. A token (GITHUB_TOKEN) lifts the search
    limit from 10 to 30 calls a minute; without one the demo still works, just fewer at a time."""
    q = urllib.parse.quote(f"repo:{owner_repo} {query}")
    data = _gh_request(f"{GITHUB_ISSUES}?q={q}&per_page={limit}")
    out = []
    for it in data.get("items", []):
        pr = it.get("pull_request")
        state = it.get("state", "")
        if pr and pr.get("merged_at"):
            state = "merged"
        out.append(Candidate(kind="pull" if pr else "issue", title=it.get("title", "")[:160], url=it.get("html_url", ""),
                             state=state, number=int(it.get("number", 0)), snippet=(it.get("body") or "")[:400]))
    return out


def _tavily(owner_repo: str, query: str, limit: int = 5) -> list[Candidate]:
    """The wider web: advisories, changelogs, discussions and forks that name the same defect."""
    name = owner_repo.split("/")[-1]
    res = get_search().search(f"{name} {query}", max_results=limit, depth="basic", include_answer=False)
    words = {w for w in re.findall(r"[a-z0-9_\-]{3,}", query.lower()) if w not in STOP}
    out = []
    for r in res.sources:
        url = r.get("url") or ""
        text = f"{r.get('title', '')} {r.get('content', '')}".lower()
        # a page that carries none of the defect's own words is the search engine free-associating
        if not url or not any(w in text for w in words):
            continue
        m = re.search(r"github\.com/([^/]+/[^/]+)/(issues|pull)/(\d+)", url)
        kind = {"issues": "issue", "pull": "pull"}.get(m.group(2), "page") if m and m.group(1).lower() == owner_repo.lower() else "page"
        out.append(Candidate(kind=kind, title=(r.get("title") or "")[:160], url=url,
                             number=int(m.group(3)) if kind != "page" else 0, snippet=(r.get("content") or "")[:400]))
    return out


def _dedupe(cands: list[Candidate], limit: int = 10) -> list[Candidate]:
    seen, out = set(), []
    # issues and pull requests from the repository itself first; the state is known for those
    for c in sorted(cands, key=lambda c: (c.kind == "page", -c.number)):
        key = (c.kind, c.number) if c.number else c.url
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out[:limit]


def _judge(claim: dict, cands: list[Candidate]) -> tuple[str, int | None, str]:
    listed = "\n".join(f"[{i}] {c.kind} #{c.number or '-'} ({c.state or 'web'}): {c.title}\n    {c.snippet[:300]}"
                       for i, c in enumerate(cands))
    text = (f"DEFECT\ntitle: {claim.get('title', '')}\nfile: {claim.get('file', '')} {claim.get('where', '')}\n"
            f"what breaks: {claim.get('what_breaks', '')}\nwhat the run showed: {(claim.get('evidence') or '')[:500]}\n\n"
            f"FOUND\n{listed}")
    raw, _ = chat(JUDGE_PROMPT, text[:9000], think=False, max_tokens=400, temperature=0, timeout=90)
    data = parse_json(raw) or {}
    status = str(data.get("status", "new")).lower()
    ref = data.get("ref")
    ref = int(ref) if isinstance(ref, (int, float)) and 0 <= int(ref) < len(cands) else None
    if status not in ("known", "fixed", "elsewhere", "new") or (status != "new" and ref is None):
        status, ref = "new", None
    # "known" and "fixed" are claims about this repository's tracker; a web page can only ever
    # say the failure is described somewhere, so a page match is "elsewhere" whatever the model said
    if ref is not None and cands[ref].kind == "page" and status in ("known", "fixed"):
        status = "elsewhere"
    if ref is not None and cands[ref].kind != "page" and status == "elsewhere":
        status = "fixed" if cands[ref].state in ("closed", "merged") else "known"
    return status, ref, str(data.get("why", ""))[:200]


def check(claim: dict, target: str) -> Known:
    """One reproduced claim in; whether upstream already knows, with the reference, out."""
    out = Known(claim=claim.get("title", ""))
    try:
        owner, name, _, _ = collect.parse_github(target)
    except ValueError as exc:
        out.error = str(exc)
        return out
    owner_repo = canonical(f"{owner}/{name}")
    out.queries = queries_for(claim, owner_repo)
    cands: list[Candidate] = []
    errors: list[str] = []

    def run(fn, q):
        try:
            return fn(owner_repo, q)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{fn.__name__.strip('_')}: {type(exc).__name__}")
            return []

    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = [pool.submit(run, fn, q) for q in out.queries for fn in (_github, _tavily)]
        for job in jobs:
            cands.extend(job.result())
    cands = _dedupe(cands)
    out.candidates = [c.__dict__ for c in cands]
    if errors:
        out.error = "; ".join(sorted(set(errors)))[:160]
        if not cands:
            return out  # status stays "unknown": the search failed, which is not the same as "new"
    if not cands:
        out.status = "new"
        out.why = "no issue, pull request or page names this file or failure"
        return out
    try:
        status, ref, why = _judge(claim, cands)
    except Exception as exc:  # noqa: BLE001
        out.error = f"judge: {type(exc).__name__}"[:160]
        return out
    out.status, out.why = status, why
    if ref is not None:
        c = cands[ref]
        out.ref = {"kind": c.kind, "number": c.number, "url": c.url, "title": c.title, "state": c.state}
    return out
