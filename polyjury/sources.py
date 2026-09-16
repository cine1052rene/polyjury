"""Where a verdict comes from, besides the run.

A reproduced defect is proof that something happens. It is not an explanation of
why that is a known bad idea. Tavily fetches the standard or the documentation that
names it, so the report can point somewhere other than at itself.
"""
from __future__ import annotations

from dataclasses import dataclass, field

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


def cite(claim: dict, limit: int = 3) -> Citation:
    """One claim in, the literature that already knows about it out."""
    query, why = _query_for(claim)
    out = Citation(claim=claim.get("title", ""), query=query, why_it_matters=why)
    try:
        result = get_search().search(query, max_results=limit, depth="basic",
                                     include_answer=False, include_domains=AUTHORITIES)
        sources = result.sources
        if not sources:  # nothing in the standards: widen to the open web
            result = get_search().search(query, max_results=limit, depth="basic",
                                         include_answer=False)
            sources = result.sources
        out.sources = [Source(title=s.get("title", "")[:160], url=s.get("url", ""),
                              snippet=(s.get("content") or "")[:320])
                       for s in sources[:limit] if s.get("url")]
    except Exception as exc:  # noqa: BLE001
        out.error = f"{type(exc).__name__}: {exc}"[:160]
    return out
