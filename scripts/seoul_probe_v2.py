"""서울판 실측 v2 — v1 문제 수정.

v1 문제: 한국어 검색에 틱톡·나무위키·SNS 잡음 / 발행일=크롤일 / 선별기가 뉴욕·과거 사실 채택 /
        최신 사실은 인용문 매칭 실패 / 한국어 생성에 외국어 토큰 섞임
v2 수정: 한국 언론·서울시 도메인 화이트리스트 / 날짜 범위·서울 여부를 코드로 검사 /
        인용문 느슨한 매칭(문자 5-gram 겹침률) / 생성문 외국어 토큰 검사
결과: scratch/case/seoul_v2.json
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

WINDOW = ("2026-09-12", "2026-09-21")  # 이번 주말 ~ 다음 주 (게임의 '오늘' 기준 창)
KR_NEWS = ["yna.co.kr", "news.kbs.co.kr", "imnews.imbc.com", "news.sbs.co.kr", "news.jtbc.co.kr",
           "donga.com", "chosun.com", "joongang.co.kr", "hani.co.kr", "khan.co.kr", "seoul.co.kr",
           "newsis.com", "news1.kr", "mk.co.kr", "hankyung.com", "edaily.co.kr", "nocutnews.co.kr",
           "news.nate.com", "v.daum.net", "n.news.naver.com", "mediahub.seoul.go.kr", "seoul.go.kr",
           "seoulmetro.co.kr", "korail.com"]
QUERIES = ["서울 지하철 운행 중단 구간", "서울 도로 전면 통제 행사", "서울 휴관 박물관 궁 공사",
           "서울 축제 행사 일정 변경 취소", "잠실 고척 경기 일정 서울"]
SEOUL = re.compile(r"서울|종로|중구|용산|성동|광진|동대문|중랑|성북|강북|도봉|노원|은평|서대문|마포|양천|강서|구로|"
                   r"금천|영등포|동작|관악|서초|강남|송파|강동|잠실|고척|광화문|여의도|홍대|명동|한강")


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
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", s or "")
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"[*_`#>|“”\"'‘’·…]", "", s)
    return re.sub(r"\s+", "", s).lower()


def overlap(quote: str, page: str, n: int = 5) -> float:
    q, p = norm(quote), norm(page)
    grams = {q[i:i + n] for i in range(max(0, len(q) - n + 1))}
    return round(sum(g in p for g in grams) / len(grams), 2) if grams else 0.0


def dates_in(s: str):
    return re.findall(r"20\d\d-\d\d-\d\d", s or "")


def in_window(scope: str) -> bool:
    ds = dates_in(scope)
    if not ds:
        return False
    start, end = min(ds), max(ds)
    return not (end < WINDOW[0] or start > WINDOW[1])


def foreign_tokens(text: str):
    # 한글 단어 안/옆에 붙은 라틴 문자열(고유명사 영문 약어 제외용으로 3자 이상 소문자 포함)
    return re.findall(r"[가-힣]*[a-z]{3,}[가-힣]+|[가-힣]+[a-z]{3,}", text or "")


def main():
    pool, seen = [], set()
    for q in QUERIES:
        s = tv.search(query=q, topic="general", country="south korea", start_date="2026-09-07",
                      filter_by_published_date=True, include_published_date=True,
                      include_domains=KR_NEWS, max_results=8, search_depth="advanced")
        rows = s.get("results", [])
        LOG["queries"].append({"q": q, "n": len(rows), "hits": [(r.get("published_date"), r["title"], r["url"]) for r in rows]})
        print(f"[search] {q} n={len(rows)}", flush=True)
        for r in rows:
            print("   -", r.get("published_date"), r["title"][:70], r["url"][:90], flush=True)
            if r["url"] not in seen:
                seen.add(r["url"])
                pool.append({"url": r["url"], "title": r["title"], "date": r.get("published_date")})
    # 본문 추출 (선별을 스니펫이 아닌 본문 기준으로)
    ex = tv.extract(urls=[p["url"] for p in pool][:20], extract_depth="advanced")
    body = {r["url"]: r.get("raw_content") or "" for r in ex.get("results", [])}
    docs = [{**p, "text": body[p["url"]][:3000]} for p in pool if body.get(p["url"])]
    print(f"\n[extract] ok={len(docs)} failed={len(ex.get('failed_results', []))}", flush=True)

    sel_raw, s_sel = chat(
        "당신은 추리 게임 단서 편집자다. 기사 본문에서 알리바이를 '엄격히 불가능'하게 만드는 확정적 사실만 고른다. "
        f"조건: (1) 장소가 서울 (2) 적용 날짜가 {WINDOW[0]}~{WINDOW[1]} 기간과 겹침 — date_scope 는 반드시 YYYY-MM-DD 형식, "
        "기사 발행일을 기준으로 '오는 14일' 같은 상대 날짜를 절대 날짜로 환산 (3) 운행중지·전면통제·휴관·경기/공연 시작시각 같은 "
        "확정 표현 (4) 사고·범죄·재난·사망·정치 주장 제외. quote 는 본문 문장을 그대로 복사. "
        '출력 JSON 배열(최대 6개): [{"url":str,"published":str,"fact":str,"quote":str,"date_scope":str,"place":str}]',
        json.dumps(docs, ensure_ascii=False, indent=1), think=True, max_tokens=7000, temp=0)
    cands = js(sel_raw) or []
    print(f"\n[select] candidates={len(cands)} ({s_sel}s)", flush=True)
    passed_facts = []
    for c in cands:
        page = body.get(c.get("url"), "")
        c["gate_window"] = in_window(c.get("date_scope", ""))
        c["gate_seoul"] = bool(SEOUL.search((c.get("place") or "") + (c.get("fact") or "")))
        c["quote_overlap"] = overlap(c.get("quote", ""), page)
        c["gate_quote"] = c["quote_overlap"] >= 0.8
        ok = c["gate_window"] and c["gate_seoul"] and c["gate_quote"]
        print(f"  {'✅' if ok else '❌'} {c.get('fact')} | scope={c.get('date_scope')} | win={c['gate_window']} "
              f"seoul={c['gate_seoul']} quote={c['quote_overlap']} | {c.get('url', '')[:80]}", flush=True)
        if ok:
            passed_facts.append(c)
    LOG["candidates"] = cands

    stories = []
    for n, d in enumerate(passed_facts[:3], 1):
        best = None
        for attempt in range(1, 3):
            story_raw, s1 = chat(
                "짧은 한국어 추리물을 쓴다. 모든 문장은 자연스러운 한국어로만 쓴다(외국어 단어 섞지 말 것). "
                "등장인물과 사건(비폭력 절도)은 가상이다. 배경은 사실의 날짜·장소다. 용의자 3명 중 정확히 1명의 알리바이만 "
                "사실에 의해 엄격히 불가능하다. 나머지 알리바이는 사실의 장소·노선·행사와 무관한 서울의 다른 곳이며 "
                "그 자체로 확인 불가능한 주장이 아니어야 한다(예: 다른 동네 카페 영수증, 다른 구 헬스장 출입기록). "
                '출력 JSON {"title":str,"setup":str,"suspects":[{"name":str,"alibi":str}],"solution":{"culprit":str,"why_impossible":str}}',
                f"사실: {d['fact']}\n원문 인용: {d['quote']}\n날짜: {d['date_scope']}\n장소: {d['place']}",
                think=True, max_tokens=5000, temp=0.7)
            story = js(story_raw)
            if not isinstance(story, dict):
                continue
            j_raw, s2 = chat(
                "추리 퍼즐 공정성 심판. 사실만 근거로 각 알리바이 판정: CONTRADICTED(엄격히 불가능)/CONSISTENT/UNCERTAIN. "
                '정답은 보지 않는다. 출력 JSON {"alibis":[{"name":str,"status":str,"evidence":str}]}',
                f"사실: {d['fact']}\n원문 인용: {d['quote']}\n날짜: {d['date_scope']}\n"
                f"용의자: {json.dumps(story['suspects'], ensure_ascii=False)}", think=True, max_tokens=3000, temp=0)
            v = js(j_raw) or {}
            st = [(a.get("name"), a.get("status")) for a in v.get("alibis", [])] if isinstance(v, dict) else []
            contra = [nm for nm, s_ in st if s_ == "CONTRADICTED"]
            fair = len(contra) == 1 and all(s_ != "UNCERTAIN" for _, s_ in st) and contra[0] == story["solution"]["culprit"]
            ft = foreign_tokens(json.dumps(story, ensure_ascii=False))
            best = {"fact": d, "attempt": attempt, "story": story, "judge": st, "fair": fair, "foreign": ft, "sec": [s1, s2]}
            print(f"\n[story #{n}.{attempt}] fair={fair} foreign={ft} ({s1}s+{s2}s)\n  제목={story.get('title')}"
                  f"\n  설정={story.get('setup')}\n  용의자={[(x['name'], x['alibi']) for x in story['suspects']]}"
                  f"\n  범인={story['solution']}\n  판정={st}", flush=True)
            if fair and not ft:
                break
        if best:
            stories.append(best)
    LOG["stories"] = stories
    (OUT / "seoul_v2.json").write_text(json.dumps(LOG, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nDONE", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        (OUT / "seoul_v2.json").write_text(json.dumps(LOG, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"!! failed: {e!r}\nDONE", flush=True)
