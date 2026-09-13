"""Collect definitive, date-bounded public facts for a city from the live web (Tavily + Nemotron)."""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

from tavily import TavilyClient

import config
from engine.cities import City
from engine.llm import chat, parse_json

Log = Callable[[str], None]


@dataclass
class Fact:
    url: str
    domain: str
    published: str | None
    fact: str
    fact_en: str
    quote: str
    date_scope: str
    place: str
    applies_to: str
    quote_overlap: float


SELECT_PROMPT = """You are the clue editor for a fair-play detective game.
From the article texts, pick facts DEFINITIVE enough to make an alibi strictly impossible, for example
"no trains between A and B on <date>", "<venue> closed on <date>", "<road> fully closed to vehicles <time>-<time> on <date>".
Rules:
1. The place must be in {city}.
2. The fact must apply on dates overlapping {start} to {end}. Convert relative dates ("this Sunday", "오는 14일")
   to absolute YYYY-MM-DD using the article's publish date.
3. Reject vague facts (delays, "some services", "expect disruption"), intermittent restrictions, accidents, crimes,
   disasters, deaths, political claims, and anything about private individuals.
4. State exactly WHO or WHAT the restriction applies to (vehicles, pedestrians, trains, visitors).
5. "quote" must be copied verbatim from the article text in its original language. "fact_en" is an English version of the fact.
Output ONLY a JSON array (max {limit} items):
[{{"url":str,"published":str,"fact":str,"fact_en":str,"quote":str,"date_scope":"YYYY-MM-DD or YYYY-MM-DD~YYYY-MM-DD","place":str,"applies_to":str}}]"""


def _norm(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text or "")
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_`#>|“”\"'‘’·…]", "", text)
    return re.sub(r"\s+", "", text).lower()


def quote_overlap(quote: str, page: str, n: int = 5) -> float:
    """Share of the quote's character n-grams found in the page (robust to markdown/spacing)."""
    q, p = _norm(quote), _norm(page)
    grams = {q[i:i + n] for i in range(max(0, len(q) - n + 1))}
    if not grams:
        return 0.0
    return round(sum(g in p for g in grams) / len(grams), 2)


def in_window(scope: str, start: str, end: str) -> bool:
    dates = re.findall(r"20\d\d-\d\d-\d\d", scope or "")
    if not dates:
        return False
    return not (max(dates) < start or min(dates) > end)


def gather_facts(city: City, today: dt.date, *, limit: int = 6, log: Log = print) -> list[Fact]:
    tv = TavilyClient(api_key=config.TAVILY_API_KEY)
    start = (today - dt.timedelta(days=1)).isoformat()
    end = (today + dt.timedelta(days=7)).isoformat()
    since = (today - dt.timedelta(days=7)).isoformat()

    pool: list[dict] = []
    seen: set[str] = set()
    for query in city.queries:
        base = dict(query=query, topic="general", country=city.tavily_country, include_published_date=True,
                    include_domains=list(city.domains), max_results=8, search_depth="advanced")
        try:
            res = tv.search(**base, start_date=since, filter_by_published_date=True)
            rows = res.get("results", [])
            if not rows:
                # Strict date filtering drops pages without a detectable date; retry with a softer recency filter.
                res = tv.search(**base, time_range="week")
                rows = res.get("results", [])
                log(f"  search [{query}] strict=0, week -> {len(rows)}")
            else:
                log(f"  search [{query}] -> {len(rows)}")
        except Exception as exc:  # noqa: BLE001
            log(f"  ! search failed [{query}]: {exc!r}")
            continue
        for r in rows:
            if r["url"] not in seen:
                seen.add(r["url"])
                pool.append({"url": r["url"], "title": r.get("title", ""), "published": r.get("published_date")})
    if not pool:
        return []

    ex = tv.extract(urls=[p["url"] for p in pool][:20], extract_depth="advanced")
    body = {r["url"]: r.get("raw_content") or "" for r in ex.get("results", [])}
    docs = [{**p, "text": body[p["url"]][:3000]} for p in pool if body.get(p["url"])]
    log(f"  extracted {len(docs)} articles")

    prompt = SELECT_PROMPT.format(city=city.name, start=start, end=end, limit=limit)
    cands: list = []
    # Long non-English inputs can make the reasoning use up the budget -> empty reply. Retry leaner and roomier.
    for text_len, max_tokens in ((3000, 8000), (1500, 16000)):
        payload = [{**d, "text": d["text"][:text_len]} for d in docs]
        raw, sec = chat(prompt, json.dumps(payload, ensure_ascii=False), think=True, max_tokens=max_tokens, temperature=0)
        parsed = parse_json(raw)
        if isinstance(parsed, list):
            cands = parsed
            log(f"  selector proposed {len(cands)} facts ({sec}s, text={text_len}, budget={max_tokens})")
            break
        log(f"  ! selector reply was not a JSON array ({sec}s, budget={max_tokens}): {raw[:200]!r}")
    if not cands:
        log("  articles seen: " + " | ".join(f"{d.get('published')} {d['title'][:60]}" for d in docs[:20]))

    published = {p["url"]: p["published"] for p in pool}
    facts: list[Fact] = []
    for c in cands:
        if not isinstance(c, dict) or not c.get("url"):
            continue
        overlap = quote_overlap(c.get("quote", ""), body.get(c["url"], ""))
        ok_window = in_window(c.get("date_scope", ""), start, end)
        ok_place = city.is_local(f"{c.get('place', '')} {c.get('fact', '')} {c.get('fact_en', '')}")
        passed = ok_window and ok_place and overlap >= 0.8
        log(f"  {'PASS' if passed else 'drop'} window={ok_window} local={ok_place} quote={overlap} | {c.get('fact_en') or c.get('fact')}")
        if passed:
            facts.append(Fact(
                url=c["url"], domain=urlparse(c["url"]).netloc.removeprefix("www."),
                published=c.get("published") or published.get(c["url"]),
                fact=c.get("fact", ""), fact_en=c.get("fact_en") or c.get("fact", ""),
                quote=c.get("quote", ""), date_scope=c.get("date_scope", ""),
                place=c.get("place", ""), applies_to=c.get("applies_to", ""), quote_overlap=overlap,
            ))
    return facts
