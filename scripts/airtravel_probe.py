"""30분 실측: 전동휠체어 항공여행 사전점검 에이전트 성립 여부.

1) Tavily 로 항공사 공식 규정 페이지를 찾아 원문 추출 (Wh 한도·인증서·사전통보가 뽑히는가)
2) Nemotron 이 경유 여정에서 가장 엄격한 규정을 고르고, 원문에 없는 건 '미확인'으로 두는가
결과는 scratch/airtravel/ 에 저장.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tavily import TavilyClient  # noqa: E402

import config  # noqa: E402
from core.nebius_client import get_client  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "scratch" / "airtravel"
OUT.mkdir(parents=True, exist_ok=True)

AIRLINES = {
    "Korean Air": "koreanair.com",
    "Lufthansa": "lufthansa.com",
    "Delta": "delta.com",
    "American Airlines": "aa.com",
    "Qantas": "qantas.com",
}
KEYWORDS = ["watt", "wh", "lithium", "battery", "48", "certificate", "notif", "removable", "배터리", "리튬"]


def step1_extract(tv: TavilyClient) -> dict:
    found = {}
    for name, domain in AIRLINES.items():
        t0 = time.time()
        rec = {"domain": domain}
        try:
            s = tv.search(
                query=f"{name} power wheelchair mobility device lithium battery watt-hour rules",
                include_domains=[domain], max_results=3, search_depth="advanced",
            )
            urls = [r["url"] for r in s.get("results", [])]
            rec["search_urls"] = urls
            if urls:
                ex = tv.extract(urls=urls[:2], extract_depth="advanced")
                pages = []
                for r in ex.get("results", []):
                    text = r.get("raw_content") or ""
                    low = text.lower()
                    pages.append({
                        "url": r.get("url"),
                        "chars": len(text),
                        "hits": {k: low.count(k) for k in KEYWORDS if low.count(k)},
                        "text": text[:12000],
                    })
                rec["pages"] = pages
                rec["failed"] = ex.get("failed_results", [])
        except Exception as e:  # noqa: BLE001
            rec["error"] = repr(e)
        rec["sec"] = round(time.time() - t0, 1)
        found[name] = rec
        print(f"[tavily] {name}: urls={len(rec.get('search_urls', []))} "
              f"pages={[(p['url'], p['chars'], p['hits']) for p in rec.get('pages', [])]} "
              f"err={rec.get('error')} {rec['sec']}s", flush=True)
    (OUT / "extract.json").write_text(json.dumps(found, ensure_ascii=False, indent=2), encoding="utf-8")
    return found


SYSTEM = """You are a pre-flight checker for travelers with power wheelchairs.
Use ONLY the airline source excerpts provided. Never use outside knowledge for rule values.
For every rule you state, cite the source URL. If a needed fact is not in the excerpts, write UNKNOWN and
say what to ask the airline. For connecting itineraries, the strictest applicable rule across all
operating carriers governs; say which carrier's rule is strictest and why.
Output JSON: {"verdict": "OK|ACTION_NEEDED|LIKELY_REFUSED|UNKNOWN",
"per_leg": [{"leg": str, "carrier": str, "rules": [{"rule": str, "value": str, "source": str}], "unknowns": [str]}],
"binding_constraints": [str], "todo_before_departure": [str], "questions_for_airline": [str]}"""


def step2_reason(found: dict) -> None:
    cli = get_client()
    excerpts = []
    for name in ("Korean Air", "Lufthansa"):
        for p in found.get(name, {}).get("pages", []):
            excerpts.append(f"### {name} <{p['url']}>\n{p['text'][:9000]}")
    scenario = (
        "Traveler: power wheelchair, lithium-ion, ONE removable battery labelled 280 Wh, "
        "plus ONE spare battery labelled 150 Wh. No manufacturer certificate on hand.\n"
        "Itinerary: Korean Air ICN->FRA, then Lufthansa FRA->BCN, departure in 30 hours.\n\n"
        "SOURCE EXCERPTS:\n" + "\n\n".join(excerpts)
    )
    raw = cli.raw
    for label, thinking in (("no_think", False), ("think", True)):
        t0 = time.time()
        r = raw.chat.completions.create(
            model=config.TEXT_MODEL,
            messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": scenario}],
            temperature=0.2, max_tokens=6000,
            extra_body={"chat_template_kwargs": {"enable_thinking": thinking}},
        )
        content = r.choices[0].message.content or ""
        (OUT / f"nemotron_{label}.txt").write_text(content, encoding="utf-8")
        print(f"\n===== Nemotron {label} ({round(time.time()-t0,1)}s, "
              f"in={r.usage.prompt_tokens} out={r.usage.completion_tokens}) =====\n{content[:5000]}", flush=True)


if __name__ == "__main__":
    tv = TavilyClient(api_key=config.TAVILY_API_KEY)
    found = step1_extract(tv)
    step2_reason(found)
    print("\nDONE", flush=True)
