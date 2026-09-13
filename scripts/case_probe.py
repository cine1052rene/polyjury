"""30분 실측: 과정 모델 게임 성립 여부.

Part A (실제 주장 수사): 최근 팩트체크 3건 → 판정 숨긴 사건파일 → 교차모델 누출검사
        → 거짓말 역할 → 모범/엉성 조사 로그 채점 차이
Part B (추리소설 × 오늘의 실제 사실): 오늘 뉴스 사실로 알리바이가 깨지는 가상 추리물 생성
        → 결정적 단서가 출처 원문에 실제 있는지 Tavily extract 로 확인
결과: scratch/case/
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
OUT.mkdir(parents=True, exist_ok=True)
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


# ---------------------------------------------------------------- Part A
FC_DOMAINS = ["factcheck.afp.com", "snopes.com", "fullfact.org", "politifact.com",
              "factcheck.org", "leadstories.com", "reuters.com", "apnews.com"]


def part_a():
    s = tv.search(query="fact check viral claim false misleading", topic="general", time_range="week",
                  include_domains=FC_DOMAINS, max_results=10, search_depth="advanced")
    picks = [r for r in s["results"] if len(r.get("content", "")) > 300][:3]
    print(f"[A] fact-check hits={len(s['results'])} picked={len(picks)}", flush=True)
    ex = tv.extract(urls=[p["url"] for p in picks], extract_depth="basic")
    texts = {r["url"]: (r.get("raw_content") or "")[:8000] for r in ex.get("results", [])}
    out = []
    for p in picks:
        src = texts.get(p["url"]) or p["content"]
        case_raw, s1 = chat(NEMO,
            "You design an investigation game. From a published fact-check, build a CASE FILE that presents the "
            "claim exactly as it circulated, WITHOUT revealing or hinting at the verdict. Hide the verdict separately. "
            "Exclude private individuals' names; public figures only if central. Output JSON: "
            '{"public_case":{"title":str,"claim_as_circulated":str,"where_it_spread":str,"first_seen_hint":str},'
            '"hidden":{"verdict":str,"key_evidence":[str],"original_context":str,"sift_path":[str]}}',
            f"FACT-CHECK SOURCE <{p['url']}>:\n{src}", think=True)
        case = js(case_raw)
        if not case:
            out.append({"url": p["url"], "error": "case json parse fail", "raw": case_raw[:500]})
            continue
        leak_raw, s2 = chat(JUDGE,
            "Given only a public case file, guess the fact-check verdict. Output JSON "
            '{"guess":"TRUE|FALSE|MISLEADING|UNSURE","leaked_hint":str|null,"confidence":0-1}',
            json.dumps(case["public_case"], ensure_ascii=False), max_tokens=400, temp=0)
        liar_raw, s3 = chat(NEMO,
            "IN-GAME ROLE: 'The Spreader', a character who defends a rumor inside a media-literacy game. "
            "Give 2 short persuasive-sounding arguments typical of misinformation tactics (appeal to emotion, "
            "cherry-picking, fake authority). Label each with the tactic name. Never invent statistics attributed "
            "to real organizations. Output JSON {\"lines\":[{\"say\":str,\"tactic\":str}]}",
            json.dumps(case["public_case"], ensure_ascii=False), think=False, max_tokens=600)
        good = ("1) Searched exact claim wording + 'fact check'. 2) Found the earliest post and checked its date. "
                "3) Looked up the account/outlet that first posted it (lateral reading). 4) Found coverage from two "
                "independent reputable outlets and the original document. 5) Compared the viral wording with the "
                "original context and noted what was changed.")
        sloppy = ("1) Read one blog that repeated the claim. 2) It had many shares and sounded confident. "
                  "3) Concluded it is true.")
        scores = {}
        for tag, logtxt in (("good", good), ("sloppy", sloppy)):
            sc_raw, _ = chat(NEMO,
                "Score a player's INVESTIGATION PROCESS (not their conclusion) with the SIFT method: "
                "Stop, Investigate the source, Find better coverage, Trace to original context. "
                'Output JSON {"S":0-2,"I":0-2,"F":0-2,"T":0-2,"total":0-8,"coach_tip":str}',
                f"CASE: {json.dumps(case['public_case'], ensure_ascii=False)}\nHIDDEN: "
                f"{json.dumps(case['hidden'], ensure_ascii=False)}\nPLAYER LOG: {logtxt}", think=True, max_tokens=2500)
            scores[tag] = js(sc_raw) or sc_raw[:300]
        rec = {"url": p["url"], "case": case, "leak_check": js(leak_raw) or leak_raw, "liar": js(liar_raw) or liar_raw,
               "scores": scores, "sec": [s1, s2, s3]}
        out.append(rec)
        print(f"\n[A] {p['url']}\n  title={case['public_case'].get('title')}\n  claim={case['public_case'].get('claim_as_circulated')}"
              f"\n  hidden_verdict={case['hidden'].get('verdict')}\n  leak_check={rec['leak_check']}"
              f"\n  liar={rec['liar']}\n  score_good={scores['good']}\n  score_sloppy={scores['sloppy']}", flush=True)
    LOG["A"] = out


# ---------------------------------------------------------------- Part B
def part_b():
    s = tv.search(query="London today disruption closure strike event", topic="news", time_range="day",
                  max_results=10, search_depth="advanced", include_published_date=True)
    facts = [{"url": r["url"], "title": r["title"], "date": r.get("published_date"), "snippet": r["content"][:500]}
             for r in s["results"]][:8]
    print(f"\n[B] today facts={len(facts)}", flush=True)
    for f in facts:
        print("  -", f["date"], f["title"][:80], f["url"], flush=True)
    story_raw, s1 = chat(NEMO,
        "Write a SHORT fictional whodunit set in the real city today. All people and the crime are fictional. "
        "Exactly one suspect's alibi must be broken by ONE real fact from the provided news items (cite its URL and "
        "quote the exact phrase that proves it). Other alibis must be consistent with the facts. Do not use real "
        "private individuals; do not depict real victims. Output JSON: "
        '{"setup":str,"suspects":[{"name":str,"alibi":str}],"solution":{"culprit":str,"breaking_fact":str,'
        '"quote":str,"source_url":str,"reasoning":str}}',
        "TODAY'S REAL NEWS ITEMS:\n" + json.dumps(facts, ensure_ascii=False, indent=1), think=True, max_tokens=5000, temp=0.7)
    story = js(story_raw)
    verify = None
    if story:
        url = story["solution"].get("source_url")
        quote = story["solution"].get("quote", "")
        try:
            ex = tv.extract(urls=[url], extract_depth="basic")
            page = (ex.get("results") or [{}])[0].get("raw_content") or ""
        except Exception as e:  # noqa: BLE001
            page = ""
            verify = {"error": repr(e)}
        if page:
            v_raw, _ = chat(JUDGE,
                "Does the SOURCE PAGE support the CLAIMED FACT (quote may be paraphrased)? Output JSON "
                '{"supported":true|false,"evidence":str}',
                f"CLAIMED FACT: {story['solution'].get('breaking_fact')}\nQUOTE: {quote}\nSOURCE PAGE:\n{page[:9000]}",
                max_tokens=500, temp=0)
            verify = js(v_raw) or v_raw
            verify["exact_quote_in_page"] = bool(quote) and quote[:60].lower() in page.lower()
    LOG["B"] = {"facts": facts, "story": story or story_raw[:1500], "verify": verify, "sec": s1}
    print(f"\n[B] story ({s1}s):\n{json.dumps(story, ensure_ascii=False, indent=1)[:3000] if story else story_raw[:1500]}"
          f"\n[B] verify={verify}", flush=True)


if __name__ == "__main__":
    for fn in (part_a, part_b):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            print(f"!! {fn.__name__} failed: {e!r}", flush=True)
    (OUT / "result.json").write_text(json.dumps(LOG, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nDONE", flush=True)
