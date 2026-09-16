"""Where a verdict comes from, besides the run.

A reproduced defect is proof that something happens. It is not an explanation of
why that is a known bad idea. Tavily fetches the standard or the documentation that
names it, so the report can point somewhere other than at itself.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import urlparse

from core.tavily_client import get_search
from engine.llm import chat, parse_json

# Places that define or document a defect class, rather than blog about it.
AUTHORITIES = [
    "cwe.mitre.org", "owasp.org", "cheatsheetseries.owasp.org", "nvd.nist.gov",
    "docs.python.org", "peps.python.org", "developer.mozilla.org", "portswigger.net",
    "datatracker.ietf.org", "docs.djangoproject.com", "flask.palletsprojects.com",
    "fastapi.tiangolo.com", "nodejs.org", "docs.npmjs.com", "kb.cert.org",
]

QUERY_PROMPT = """Turn this defect into one search query that would find the standard,
specification or official documentation that names this class of problem.
Use the vocabulary of that literature, not the words of this particular project.
Never mention the project, the file or the function.

Answer with JSON only: {"query": str, "why_it_matters": str (max 25 words)}"""


@dataclass
class Source:
    title: str
    url: str
    snippet: str


@dataclass
class Citation:
    claim: str
    query: str = ""
    why_it_matters: str = ""
    sources: list[Source] = field(default_factory=list)
    error: str = ""


def _query_for(claim: dict) -> tuple[str, str]:
    text = (f"{claim.get('title', '')}\n{claim.get('what_breaks', '')}\n"
            f"file: {claim.get('file', '')}")
    try:
        raw, _ = chat(QUERY_PROMPT, text[:4000], think=False, max_tokens=500,
                      temperature=0, timeout=60)
        data = parse_json(raw) or {}
        query = (data.get("query") or "").strip()
        if query:
            return query, (data.get("why_it_matters") or "").strip()
    except Exception:  # noqa: BLE001
        pass
    return claim.get("title", "")[:120], ""


STOPWORDS = {"the", "a", "an", "of", "via", "and", "or", "in", "on", "to", "for", "with", "by"}


def _search(query: str, limit: int, only_authorities: bool) -> list[dict]:
    try:
        return get_search().search(
            query, max_results=limit, depth="basic", include_answer=False,
            include_domains=AUTHORITIES if only_authorities else None).sources
    except Exception:  # noqa: BLE001
        return []


def _from_authority(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return any(host == d or host.endswith("." + d) for d in AUTHORITIES)


def _looks_relevant(item: dict, query: str) -> bool:
    """Tavily sometimes ignores include_domains and answers the query word by word,
    so a search for a header-spoofing bypass comes back with a dictionary entry for
    'rate'. Keep only results that actually carry the query's own vocabulary."""
    words = {w for w in re.findall(r"[a-z0-9-]{4,}", query.lower()) if w not in STOPWORDS}
    if not words:
        return True
    text = f"{item.get('title', '')} {item.get('content', '')}".lower()
    hits = sum(1 for w in words if w in text)
    return hits >= max(2, len(words) // 3)


def cite(claim: dict, limit: int = 3) -> Citation:
    """One claim in, the literature that already knows about it out."""
    query, why = _query_for(claim)
    out = Citation(claim=claim.get("title", ""), query=query, why_it_matters=why)
    try:
        # The domain filter is unreliable and its results vary between calls, so both
        # searches run and the authoritative hits are preferred from the combined pool.
        pool: list[dict] = []
        with ThreadPoolExecutor(max_workers=2) as run:
            jobs = [run.submit(_search, query, limit * 3, True),
                    run.submit(_search, query, limit * 3, False)]
            for job in jobs:
                pool.extend(job.result())
        keep = [r for r in pool if r.get("url") and _from_authority(r["url"])]
        if not keep:  # the standards have nothing on it: widen, but stay on topic
            keep = [r for r in pool if r.get("url") and _looks_relevant(r, query)]
        seen, picked = set(), []
        for item in keep:
            host = urlparse(item["url"]).hostname or item["url"]
            if host in seen:
                continue
            seen.add(host)
            picked.append(Source(title=(item.get("title") or "")[:160], url=item["url"],
                                 snippet=(item.get("content") or "")[:320]))
            if len(picked) == limit:
                break
        out.sources = picked
    except Exception as exc:  # noqa: BLE001
        out.error = f"{type(exc).__name__}: {exc}"[:160]
    return out
