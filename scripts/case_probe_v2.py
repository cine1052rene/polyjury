"""v2: 실측에서 드러난 3가지 문제를 고칠 수 있는가.

A2-1 최신성: filter_by_published_date + start_date 로 오래된 팩트체크 제거되는가
A2-2 거짓말 역할: 퍼진 문장만 변형 + 교차모델이 '새 사실 주입' 검사
B2   추리물 공정성: 알리바이별 판정(모순/일관/불확실) → 정답 유일할 때까지 재생성(최대 3회)
결과: scratch/case/v2.json
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
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except Exception:  # noqa: BLE001
        return None


FC_DOMAINS = ["factcheck.afp.com", "snopes.com", "fullfact.org", "politifact.com",
              "factcheck.org", "leadstories.com", "reuters.com", "apnews.com"]


def a2():
    s = tv.search(query="fact check viral claim", topic="news", start_date="2026-09-01",
                  filter_by_published_date=True, include_published_date=True,
                  include_domains=FC_DOMAINS, max_results=10, search_depth="advanced")
    rows = [{"date": r.get("published_date"), "url": r["url"], "title": r["title"]} for r in s["results"]]
    print(f"[A2-1] fresh fact-checks={len(rows)}", flush=True)
    for r in rows:
        print("  -", r["date"], r["title"][:90], r["url"], flush=True)
    LOG["fresh"] = rows

    prev = json.loads((OUT / "result.json").read_text(encoding="utf-8"))["A"]
    liar_out = []
    for rec in prev:
        claim = rec["case"]["public_case"]["claim_as_circulated"]
        liar_raw, _ = chat(NEMO,
            "IN-GAME ROLE 'The Spreader' in a media-literacy game. You may ONLY restate the circulating claim below "
            "using a manipulation tactic (emotional framing, urgency, us-vs-them, false certainty). HARD RULES: add no "
            "new facts, numbers, names, organizations, documents, quotes or sources that are not already in the claim. "
            'Output JSON {"lines":[{"say":str,"tactic":str}]} with 2 lines.',
            f"CIRCULATING CLAIM: {claim}", think=False, max_tokens=500)
        liar = js(liar_raw) or {"lines": []}
        audit_raw, _ = chat(JUDGE,
            "Compare LINES to the ORIGINAL CLAIM. List any factual assertion in LINES that is NOT present in the "
            "ORIGINAL CLAIM (new numbers, people, organizations, documents, events, sources). Rhetorical framing is "
            'allowed. Output JSON {"new_assertions":[str],"pass":true|false}',
            f"ORIGINAL CLAIM: {claim}\nLINES: {json.dumps(liar, ensure_ascii=False)}", max_tokens=500, temp=0)
        audit = js(audit_raw) or audit_raw
        liar_out.append({"claim": claim, "liar": liar, "audit": audit})
        print(f"\n[A2-2] claim={claim[:100]}\n  liar={liar}\n  audit={audit}", flush=True)
    LOG["liar_v2"] = liar_out


SAFE_TOPICS = re.compile(r"(?i)flight|rail|train|airport|closure|delay|weather|forecast|football|match|tube|road|festival")


def b2():
    prev = json.loads((OUT / "result.json").read_text(encoding="utf-8"))["B"]["facts"]
    facts = [f for f in prev if SAFE_TOPICS.search(f["title"])]
    ex = tv.extract(urls=[f["url"] for f in facts], extract_depth="basic")
    body = {r["url"]: (r.get("raw_content") or "")[:2500] for r in ex.get("results", [])}
    for f in facts:
        f["text"] = body.get(f["url"], f["snippet"])
    print(f"\n[B2] safe facts={len(facts)}: {[f['title'][:50] for f in facts]}", flush=True)
    facts_blob = json.dumps(facts, ensure_ascii=False, indent=1)
    attempts = []
    for n in range(1, 4):
        feedback = "" if not attempts else f"\nPREVIOUS ATTEMPT FAILED FAIR-PLAY CHECK: {attempts[-1]['judge_summary']}"
        story_raw, s1 = chat(NEMO,
            "Write a SHORT fictional whodunit set in London on Sunday 13 Sep 2026. All people and the crime are "
            "fictional and non-violent (theft). Exactly ONE suspect's alibi must be made STRICTLY IMPOSSIBLE by one "
            "fact in the articles (entailment, not just 'delays'). Every other alibi must NOT touch any service, place or "
            "event mentioned in the articles, so it cannot be contradicted. Quote the exact sentence from the article text. "
            'Output JSON {"setup":str,"suspects":[{"name":str,"alibi":str}],"solution":{"culprit":str,"quote":str,'
            '"source_url":str,"why_impossible":str}}' + feedback,
            "ARTICLES:\n" + facts_blob, think=True, max_tokens=6000, temp=0.7)
        story = js(story_raw)
        if not story:
            attempts.append({"n": n, "error": "parse", "judge_summary": "invalid JSON"})
            continue
        verdicts = {}
        for judge_model, think in ((NEMO, True), (JUDGE, None)):
            j_raw, s2 = chat(judge_model,
                "FAIR-PLAY JUDGE for a mystery puzzle. For EACH alibi decide using ONLY the article texts: "
                "CONTRADICTED (article facts make it strictly impossible), CONSISTENT (no article fact conflicts), or "
                "UNCERTAIN (articles suggest a problem but do not make it impossible). Do not use the proposed solution. "
                'Output JSON {"alibis":[{"name":str,"status":str,"evidence":str}],"unique_solution":true|false}',
                "ARTICLES:\n" + facts_blob + "\nSUSPECTS:\n" + json.dumps(story["suspects"], ensure_ascii=False),
                think=think, max_tokens=4000, temp=0)
            verdicts[judge_model.split("/")[-1]] = js(j_raw) or j_raw[:500]
        def ok(v):
            if not isinstance(v, dict):
                return False
            st = [a.get("status") for a in v.get("alibis", [])]
            contra = [a.get("name") for a in v.get("alibis", []) if a.get("status") == "CONTRADICTED"]
            return st.count("CONTRADICTED") == 1 and st.count("UNCERTAIN") == 0 and contra[0] == story["solution"]["culprit"]
        passed = all(ok(v) for v in verdicts.values())
        summary = {k: [(a.get("name"), a.get("status")) for a in v.get("alibis", [])] if isinstance(v, dict) else "parse"
                   for k, v in verdicts.items()}
        attempts.append({"n": n, "story": story, "verdicts": verdicts, "passed": passed,
                         "judge_summary": json.dumps(summary, ensure_ascii=False), "gen_sec": s1})
        print(f"\n[B2] attempt {n} ({s1}s) culprit={story['solution'].get('culprit')} passed={passed}\n"
              f"  suspects={[(x['name'], x['alibi'][:110]) for x in story['suspects']]}\n"
              f"  quote={story['solution'].get('quote')}\n  judges={summary}", flush=True)
        if passed:
            break
    LOG["mystery_v2"] = attempts


if __name__ == "__main__":
    for fn in (a2, b2):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            print(f"!! {fn.__name__} failed: {e!r}", flush=True)
    (OUT / "v2.json").write_text(json.dumps(LOG, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nDONE", flush=True)
