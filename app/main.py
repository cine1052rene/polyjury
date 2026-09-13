"""Factdunit web API + static front end.

    uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import sys
import time
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from tavily import TavilyClient  # noqa: E402

import config  # noqa: E402
from engine import store  # noqa: E402
from engine.cities import CITIES  # noqa: E402
from engine.grading import grade  # noqa: E402

app = FastAPI(title="Factdunit")

SEARCH_TTL = 3600
RATE_LIMIT, RATE_WINDOW = 30, 600          # searches per client per 10 minutes
_search_cache: dict[str, tuple[float, list[dict]]] = {}
_result_by_url: dict[str, dict] = {}
_rate: dict[str, deque] = defaultdict(deque)
_tavily: TavilyClient | None = None


def tavily() -> TavilyClient:
    global _tavily
    if _tavily is None:
        _tavily = TavilyClient(api_key=config.TAVILY_API_KEY)
    return _tavily


class SearchIn(BaseModel):
    city: str
    query: str = Field(min_length=2, max_length=200)


class Evidence(BaseModel):
    url: str
    title: str = ""
    snippet: str = ""
    published: str | None = None


class ProcessLog(BaseModel):
    elapsed_sec: int = 0
    queries: list[str] = Field(default_factory=list)
    opened: list[str] = Field(default_factory=list)


class AccuseIn(BaseModel):
    case_id: str
    suspect_id: str
    evidence: Evidence | None = None
    process: ProcessLog = Field(default_factory=ProcessLog)


def _client_key(request: Request) -> str:
    return request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "?")


def _check_rate(key: str) -> None:
    now, q = time.time(), _rate[key]
    while q and now - q[0] > RATE_WINDOW:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        raise HTTPException(429, "Too many searches. Take a breath, detective — try again in a few minutes.")
    q.append(now)


@app.get("/api/cities")
def cities() -> list[dict]:
    out = []
    for city in CITIES.values():
        case = store.latest_case(city.id)
        out.append({"id": city.id, "name": city.name, "name_local": city.name_local,
                    "case_date": case["date"] if case else None})
    return out


@app.get("/api/case/{city_id}")
def get_case(city_id: str) -> dict:
    if city_id not in CITIES:
        raise HTTPException(404, "unknown city")
    case = store.latest_case(city_id)
    if case is None:
        raise HTTPException(404, "no case yet for this city")
    return store.public_view(case)


@app.post("/api/search")
def search(body: SearchIn, request: Request) -> dict:
    city = CITIES.get(body.city)
    if city is None:
        raise HTTPException(404, "unknown city")
    query = " ".join(body.query.split())
    key = f"{city.id}|{query.lower()}"
    cached = _search_cache.get(key)
    if cached and time.time() - cached[0] < SEARCH_TTL:
        return {"query": query, "results": cached[1], "cached": True}
    _check_rate(_client_key(request))
    try:
        res = tavily().search(query=query, topic="general", country=city.tavily_country, max_results=6,
                              search_depth="basic", include_published_date=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"search failed: {exc.__class__.__name__}") from exc
    results = []
    for r in res.get("results", []):
        item = {"url": r["url"], "title": r.get("title", ""), "domain": urlparse(r["url"]).netloc.removeprefix("www."),
                "published": r.get("published_date"), "snippet": (r.get("content") or "")[:280]}
        _result_by_url[r["url"]] = {**item, "snippet": (r.get("content") or "")[:1500]}
        results.append(item)
    _search_cache[key] = (time.time(), results)
    return {"query": query, "results": results, "cached": False}


@app.post("/api/accuse")
def accuse(body: AccuseIn) -> dict:
    case = store.load_case_by_id(body.case_id)
    if case is None:
        raise HTTPException(404, "case not found")
    evidence = None
    if body.evidence:
        evidence = _result_by_url.get(body.evidence.url) or {**body.evidence.model_dump(), "snippet": body.evidence.snippet[:600]}
    try:
        return grade(case, body.suspect_id, evidence, body.process.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
