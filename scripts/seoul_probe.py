"""서울판 실측: 한국어 뉴스 → 확정적 사실 선별 → 한국어 추리물 → 공정성 판정 → 원문 인용 확인.

확인할 것
1) Tavily 가 한국어 최신 뉴스에서 '확정적' 사실(운행중지·통제·휴관·경기 일정)을 충분히 가져오는가
2) Nemotron 이 한국어로 사실 선별·추리물 생성·공정성 판정을 제대로 하는가
3) 선별 인용문이 원문에 실제로 있는가 (마크다운 제거 후 매칭)
결과: scratch/case/seoul.json
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
raw = get_client().raw
tv = TavilyClient(api_key=config.TAVILY_API_KEY)
LOG: dict = {"queries": []}

QUERIES = [
    "서울 지하철 운행 중단 구간 주말",
    "서울 도로 교통 통제 행사 주말",
    "서울 박물관 미술관 휴관 임시 휴관",
    "서울 축제 행사 취소 연기",
    "잠실 경기 결과 프로야구 서울",
]


def chat(system, user, think, max_tokens=5000, temp=0.3):
    t0 = time.time()
    r = raw.chat.completions.create(
        model=NEMO, temperature=temp, max_tokens=max_tokens,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        extra_body={"chat_template_kwargs": {"enable_thinking": think}})
    return (r.choices[0].message.content or "").strip(), round(time.time() - t0, 1)


def js(text):
    m = re.search(r"[\{\[].*[\}\]]", text, re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except Exception:  # noqa: BLE001
        return None


def norm(s: str) -> str:
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", s)           # 이미지
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)        # 링크
    s = re.sub(r"[*_`#>|]", "", s)                         # 마크다운 기호
    return re.sub(r"\s+", "", s).lower()                   # 공백 제거


def search(q):
    base = dict(query=q, topic="general", country="south korea", time_range="week",
                max_results=6, search_depth="advanced", include_published_date=True)
    try:
        return tv.search(**base, filter_by_published_date=True), "filtered"
    except Exception:  # noqa: BLE001
        return tv.search(**base), "unfiltered"


def main():
    pool, seen = [], set()
    for q in QUERIES:
        t0 = time.time()
        s, mode = search(q)
        rows = s.get("results", [])
        LOG["queries"].append({"q": q, "mode": mode, "n": len(rows), "sec": round(time.time() - t0, 1),
                               "hits": [(r.get("published_date"), r["title"], r["url"]) for r in rows]})
        print(f"[search] {q} ({mode}) n={len(rows)}", flush=True)
        for r in rows:
            print("   -", r.get("published_date"), r["title"][:70], r["url"], flush=True)
            if r["url"] not in seen:
                seen.add(r["url"])
                pool.append({"url": r["url"], "title": r["title"], "date": r.get("published_date"),
                             "snippet": r["content"][:700]})

    sel_raw, s_sel = chat(
        "당신은 추리 게임의 단서 편집자다. 아래 한국 뉴스 조각에서 알리바이를 '엄격히 불가능'하게 만들 만큼 "
        "확정적인 사실만 고른다. 예: '○월 ○일 ○호선 A~B역 구간 열차 운행 중단', '○일 ○○박물관 휴관', "
        "'○일 ○○대로 전면 통제 ○시~○시', '○일 잠실 경기 ○시 시작'. "
        "제외: '지연·혼잡 예상' 같은 모호한 것, 사고·범죄·재난·사망 등 비극적 사건, 정치 집회 자체의 주장, 사적 개인 정보. "
        "quote 는 뉴스 조각에 있는 문장을 한 글자도 바꾸지 말고 그대로 복사한다. "
        '출력 JSON 배열(최대 5개): [{"url":str,"fact":str,"quote":str,"date_scope":str,"place":str}]',
        json.dumps(pool, ensure_ascii=False, indent=1), think=True, max_tokens=6000, temp=0)
    defs = js(sel_raw) or []
    print(f"\n[select] pool={len(pool)} definitive={len(defs)} ({s_sel}s)", flush=True)

    # 인용문 원문 확인
    urls = list({d["url"] for d in defs if d.get("url")})
    pages = {}
    if urls:
        ex = tv.extract(urls=urls, extract_depth="advanced")
        pages = {r["url"]: r.get("raw_content") or "" for r in ex.get("results", [])}
        LOG["extract_failed"] = ex.get("failed_results")
    for d in defs:
        page = pages.get(d.get("url"), "")
        snippet = next((p["snippet"] for p in pool if p["url"] == d.get("url")), "")
        q = norm(d.get("quote", ""))[:40]
        d["quote_in_page"] = bool(q) and q in norm(page)
        d["quote_in_snippet"] = bool(q) and q in norm(snippet)
        d["page_len"] = len(page)
        print("  *", d, flush=True)
    LOG["definitive"] = defs

    attempts = []
    for n, d in enumerate([x for x in defs if x.get("quote_in_page") or x.get("quote_in_snippet")][:3], 1):
        story_raw, s1 = chat(
            "짧은 한국어 추리물을 쓴다. 등장인물과 사건(비폭력 절도)은 모두 가상이다. 배경은 사실의 날짜·장소다. "
            "용의자 3명 중 정확히 1명의 알리바이만 주어진 사실에 의해 '엄격히 불가능'해야 한다. "
            "나머지 알리바이는 사실에 등장하는 노선·장소·행사와 전혀 무관해야 한다. 실존 개인을 쓰지 않는다. "
            '출력 JSON {"title":str,"setup":str,"suspects":[{"name":str,"alibi":str}],'
            '"solution":{"culprit":str,"why_impossible":str}}',
            f"사실: {d.get('fact')}\n원문 인용: {d.get('quote')}\n날짜 범위: {d.get('date_scope')}\n장소: {d.get('place')}",
            think=True, max_tokens=5000, temp=0.7)
        story = js(story_raw)
        if not isinstance(story, dict):
            attempts.append({"n": n, "error": "parse", "raw": story_raw[:400]})
            print(f"[story #{n}] parse fail", flush=True)
            continue
        j_raw, s2 = chat(
            "추리 퍼즐 공정성 심판. 주어진 사실만 근거로 각 알리바이를 판정한다: "
            "CONTRADICTED(사실상 엄격히 불가능), CONSISTENT(충돌 없음), UNCERTAIN(의심되나 불가능하다고 단정 불가). "
            '제안된 정답은 보지 않는다. 출력 JSON {"alibis":[{"name":str,"status":str,"evidence":str}]}',
            f"사실: {d.get('fact')}\n원문 인용: {d.get('quote')}\n날짜 범위: {d.get('date_scope')}\n"
            f"용의자: {json.dumps(story['suspects'], ensure_ascii=False)}",
            think=True, max_tokens=3000, temp=0)
        v = js(j_raw) or {}
        st = [(a.get("name"), a.get("status")) for a in v.get("alibis", [])] if isinstance(v, dict) else []
        contra = [nm for nm, s_ in st if s_ == "CONTRADICTED"]
        passed = len(contra) == 1 and all(s_ != "UNCERTAIN" for _, s_ in st) and contra[0] == story["solution"]["culprit"]
        attempts.append({"n": n, "fact": d, "story": story, "judge": v, "passed": passed, "sec": [s1, s2]})
        print(f"\n[story #{n}] passed={passed} ({s1}s+{s2}s)\n  제목={story.get('title')}\n  설정={story.get('setup')}"
              f"\n  용의자={[(x['name'], x['alibi']) for x in story['suspects']]}\n  범인={story['solution']}"
              f"\n  판정={st}", flush=True)
    LOG["stories"] = attempts
    (OUT / "seoul.json").write_text(json.dumps(LOG, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nDONE", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        (OUT / "seoul.json").write_text(json.dumps(LOG, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"!! failed: {e!r}\nDONE", flush=True)
