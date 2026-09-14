"""Rebuild probe: can today's trends become 'humans vs Nemotron' forecast questions that reality settles soon?

1) Google Trends RSS (KR, US, GB, JP) -> trending keywords + related news titles
2) Nemotron (thinking on) turns them into yes/no questions that resolve within 72h from public news,
   and commits to its own probability + short reasoning + what would change its mind.
Result: scratch/forecast/probe.json
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.llm import chat, parse_json  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "scratch" / "forecast"
OUT.mkdir(parents=True, exist_ok=True)
NS = {"ht": "https://trends.google.com/trending/rss"}
GEOS = ["KR", "US", "GB", "JP"]


def trends(geo: str, limit: int = 12) -> list[dict]:
    req = urllib.request.Request(f"https://trends.google.com/trending/rss?geo={geo}", headers={"User-Agent": "Mozilla/5.0"})
    root = ET.fromstring(urllib.request.urlopen(req, timeout=30).read())
    items = []
    for it in root.iter("item"):
        news = [n.findtext("ht:news_item_title", default="", namespaces=NS) for n in it.findall("ht:news_item", NS)]
        items.append({"geo": geo, "keyword": it.findtext("title", default=""),
                      "traffic": it.findtext("ht:approx_traffic", default="", namespaces=NS),
                      "published": it.findtext("pubDate", default=""), "news": [n for n in news if n][:3]})
    return items[:limit]


PROMPT = """You design questions for a public game: "Can people read the world better than an AI?"
From today's trending searches, write up to 8 YES/NO questions about what will happen next.
Rules:
- Must resolve within 72 hours (by {deadline} UTC) from public news, with a clear resolution rule.
- Not already decided at question time; genuinely uncertain (you would not give below 10% or above 90%).
- Interesting to ordinary people (sports, entertainment, tech launches, markets, weather, politics outcomes are fine).
- No deaths, crimes by named people, health of individuals, disasters with victims, or private persons.
For each, commit to YOUR forecast before anyone else plays.
Output ONLY JSON array:
[{{"geo":str,"keyword":str,"question":str,"resolves_by":str,"resolution_rule":str,
"ai_probability_yes":0-100,"ai_reasoning":str (max 35 words),"what_would_change_my_mind":str (max 20 words)}}]"""


def main() -> None:
    pool = []
    for geo in GEOS:
        try:
            got = trends(geo)
            pool += got
            print(f"[trends] {geo}: {len(got)} -> {[g['keyword'] for g in got]}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[trends] {geo} failed: {exc!r}", flush=True)
    deadline = time.strftime("%Y-%m-%d %H:%M", time.gmtime(time.time() + 72 * 3600))
    raw, sec = chat(PROMPT.format(deadline=deadline), json.dumps(pool, ensure_ascii=False),
                    think=True, max_tokens=12000, temperature=0.4)
    qs = parse_json(raw)
    print(f"\n[questions] {len(qs) if isinstance(qs, list) else 'parse fail'} ({sec}s)", flush=True)
    for q in qs if isinstance(qs, list) else []:
        print(f"\n- [{q.get('geo')}] {q.get('question')}\n  by {q.get('resolves_by')} | rule: {q.get('resolution_rule')}"
              f"\n  AI: {q.get('ai_probability_yes')}% YES — {q.get('ai_reasoning')}\n  would change mind: {q.get('what_would_change_my_mind')}", flush=True)
    (OUT / "probe.json").write_text(json.dumps({"trends": pool, "questions": qs, "raw": raw if not isinstance(qs, list) else ""},
                                               ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nDONE", flush=True)


if __name__ == "__main__":
    main()
