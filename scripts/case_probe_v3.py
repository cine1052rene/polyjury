"""v3: (A3) 팩트체크 전용 도메인 + 발행일 필터로 '오늘의 사건' 소스가 깨끗한가
       (B3) '확정적 사실'만 골라 쓰면 공정성(정답 유일) 판정을 통과하는가
결과: scratch/case/v3.json
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tavily import TavilyClient  # noqa: E402

import config  # noqa: E402
from core.nebius_client import get_client  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "scratch" / "case"
NEMO = config.TEXT_MODEL
JUDGE = "Qwen/Qwen3-235B-A22B-Instruct-2507"
raw = get_client().raw
tv = TavilyClient(api_key=config.TAVILY_API_KEY)
LOG: dict = {}


def chat(model, system, user, think=None, max_tokens=4000, temp=0.3):
    kw = {}
    if think is not None:
        kw["extra_body"] = {"chat_template_kwargs": {"enable_thinking": think}}
    t0 = time.time()
    r = raw.chat.completions.create(model=model, temperature=temp, max_tokens=max_tokens,
                                    messages=[{"role": "system", "content": system},
                                              {"role": "user", "content": user}], **kw)
    return (r.choices[0].message.content or "").strip(), round(time.time() - t0, 1)


def js(text):
    m = re.search(r"[\{\[].*[\}\]]", text, re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except Exception:  # noqa: BLE001
        return None


def a3():
    doms = ["factcheck.afp.com", "snopes.com", "fullfact.org", "politifact.com", "factcheck.org",
            "leadstories.com", "checkyourfact.com", "healthfeedback.org", "logically.ai"]
    s = tv.search(query="fact check", topic="general", start_date="2026-09-01", filter_by_published_date=True,
                  include_published_date=True, include_domains=doms, max_results=15, search_depth="advanced")
    rows = [{"date": r.get("published_date"), "url": r["url"], "title": r["title"]} for r in s["results"]]
    print(f"[A3] fact-check-only fresh={len(rows)}", flush=True)
    for r in rows:
        print("  -", r["date"], r["title"][:90], r["url"], flush=True)
    LOG["A3"] = rows


def b3():
    queries = ["London station closed all day no trains Sunday", "London museum closed today",
               "London road closed all day event Sunday", "London match final score Sunday"]
    pool = []
    for q in queries:
        s = tv.search(query=q, topic="news", time_range="week", max_results=5, search_depth="advanced",
                      include_published_date=True)
        pool += [{"url": r["url"], "title": r["title"], "date": r.get("published_date"), "snippet": r["content"][:600]}
                 for r in s["results"]]
    seen, uniq = set(), []
    for p in pool:
        if p["url"] not in seen:
            seen.add(p["url"]); uniq.append(p)
    sel_raw, _ = chat(NEMO,
        "From these news snippets, select facts that are DEFINITIVE enough to make an alibi strictly impossible "
        "(e.g., 'station closed all day, no trains', 'museum closed on Sunday 13 Sep', 'match kicked off at 3pm at X'). "
        "Reject vague ones (delays, 'some services', 'expect disruption'), violent/tragic events, and anything about "
        'private individuals. Output JSON [{"url":str,"fact":str,"quote":str,"date_scope":str}] (max 4).',
        json.dumps(uniq, ensure_ascii=False, indent=1), think=True, max_tokens=4000, temp=0)
    defs = js(sel_raw) or []
    print(f"[B3] pool={len(uniq)} definitive={len(defs)}", flush=True)
    for d in defs:
        print("  *", d, flush=True)
    attempts = []
    for n, d in enumerate(defs[:3], 1):
        story_raw, s1 = chat(NEMO,
            "Write a SHORT fictional, non-violent whodunit (a theft) set on the date/place of the fact. All people are "
            "fictional. Exactly ONE suspect's alibi must be made STRICTLY IMPOSSIBLE by the FACT. Other alibis must not "
            "touch anything in the fact. Output JSON {\"setup\":str,\"suspects\":[{\"name\":str,\"alibi\":str}],"
            "\"solution\":{\"culprit\":str,\"why_impossible\":str}}",
            f"FACT: {d.get('fact')}\nQUOTE: {d.get('quote')}\nSCOPE: {d.get('date_scope')}\nSOURCE: {d.get('url')}",
            think=True, max_tokens=4000, temp=0.7)
        story = js(story_raw)
        if not isinstance(story, dict):
            attempts.append({"n": n, "error": "parse"}); continue
        j_raw, s2 = chat(NEMO,
            "FAIR-PLAY JUDGE. Using ONLY the fact, label each alibi CONTRADICTED (strictly impossible), CONSISTENT, or "
            'UNCERTAIN. Output JSON {"alibis":[{"name":str,"status":str,"evidence":str}]}',
            f"FACT: {d.get('fact')}\nQUOTE: {d.get('quote')}\nSCOPE: {d.get('date_scope')}\nSUSPECTS: "
            + json.dumps(story["suspects"], ensure_ascii=False), think=True, max_tokens=3000, temp=0)
        v = js(j_raw) or {}
        st = [(a.get("name"), a.get("status")) for a in v.get("alibis", [])] if isinstance(v, dict) else []
        contra = [nm for nm, s_ in st if s_ == "CONTRADICTED"]
        passed = len(contra) == 1 and not any(s_ == "UNCERTAIN" for _, s_ in st) and contra[0] == story["solution"]["culprit"]
        # 원문에서 인용문 존재 확인
        try:
            page = (tv.extract(urls=[d["url"]], extract_depth="basic").get("results") or [{}])[0].get("raw_content") or ""
        except Exception:  # noqa: BLE001
            page = ""
        quote_found = bool(d.get("quote")) and d["quote"][:50].lower() in page.lower()
        attempts.append({"n": n, "fact": d, "story": story, "judge": v, "passed": passed, "quote_in_page": quote_found})
        print(f"\n[B3] #{n} passed={passed} quote_in_page={quote_found} ({s1}s+{s2}s)\n  fact={d.get('fact')}\n"
              f"  suspects={[(x['name'], x['alibi'][:120]) for x in story['suspects']]}\n  culprit={story['solution']['culprit']}"
              f"\n  judge={st}", flush=True)
    LOG["B3"] = attempts


if __name__ == "__main__":
    for fn in (a3, b3):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            print(f"!! {fn.__name__} failed: {e!r}", flush=True)
    (OUT / "v3.json").write_text(json.dumps(LOG, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nDONE", flush=True)
