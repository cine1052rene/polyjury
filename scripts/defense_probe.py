"""변호인 에이전트 실측: 판정자의 '가정' 오류를 잡아내는가.

기존 퍼즐 6개(서울 v2 3개 + 런던 v3 3개)의 '범인 알리바이'에 대해
변호인(Nemotron 생각모드)이 사실과 모순되지 않는 해석을 찾으려 시도 → 찾으면 '불가능' 아님.
사람(Claude) 수동 라벨과 비교해 정확도 측정.
결과: scratch/case/defense.json
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from core.nebius_client import get_client  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "scratch" / "case"
NEMO = config.TEXT_MODEL
raw = get_client().raw

# 수동 라벨: True = 범인 알리바이가 사실에 의해 정말 불가능(공정), False = 가능한 해석이 있음(불공정)
LABELS = {
    "seoul#1": (False, "소월로 통제는 6~7차례 간헐적 → 연속 운전 불가능 단정 못함"),
    "seoul#2": (False, "도로 통제는 걷기축제용 차량 통제 → 도보 이동은 가능"),
    "seoul#3": (False, "8시 DDP 출발은 참가자 얘기, 용의자는 참가자라는 전제 없음"),
    "london#1": (True, "해당 구간 종일 무운행인데 그 구간 열차 탑승 주장"),
    "london#2": (True, "9시까지 해당 구간 무운행인데 8:15 탑승 주장"),
    "london#3": (True, "역 주말 전면 폐쇄(심야 포함)인데 새벽 1시 역 안 커피숍 주장 — 역 밖 매장 해석 여지 약간"),
}


def chat(system, user, think=True, max_tokens=3000, temp=0):
    t0 = time.time()
    r = raw.chat.completions.create(
        model=NEMO, temperature=temp, max_tokens=max_tokens,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        extra_body={"chat_template_kwargs": {"enable_thinking": think}})
    return (r.choices[0].message.content or "").strip(), round(time.time() - t0, 1)


def js(text):
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except Exception:  # noqa: BLE001
        return None


def load_cases():
    cases = []
    seoul = json.loads((OUT / "seoul_v2.json").read_text(encoding="utf-8"))["stories"]
    for i, s in enumerate(seoul, 1):
        f = s["fact"]
        cases.append({"id": f"seoul#{i}", "lang": "ko", "fact": f["fact"], "quote": f["quote"],
                      "scope": f["date_scope"], "story": s["story"]})
    london = json.loads((OUT / "v3.json").read_text(encoding="utf-8"))["B3"]
    for i, s in enumerate(london, 1):
        if "story" not in s:
            continue
        f = s["fact"]
        cases.append({"id": f"london#{i}", "lang": "en", "fact": f["fact"], "quote": f["quote"],
                      "scope": f["date_scope"], "story": s["story"]})
    return cases


DEFENSE = (
    "You are the DEFENSE ATTORNEY in a fair-play mystery. The prosecution says the suspect's alibi is STRICTLY "
    "IMPOSSIBLE given a real-world fact. Try hard to find ANY reasonable reading in which the alibi is still true "
    "WITHOUT contradicting the fact text. Check especially: who/what the restriction applies to (vehicles vs "
    "pedestrians, participants vs everyone), whether it is continuous or intermittent, exact place boundaries "
    "(inside vs near), exact time windows, and unstated assumptions in the alibi. Do not invent new facts. "
    'Output JSON {"alibi_can_be_true":true|false,"best_defense":str,"assumption_exposed":str|null}'
)
JUDGE = (
    "You are the JUDGE. Given the fact, the alibi, and the defense argument, decide if the alibi is STRICTLY "
    "IMPOSSIBLE. If the defense shows a reasonable reading consistent with the fact text, the answer is NOT impossible. "
    'Output JSON {"strictly_impossible":true|false,"reason":str}'
)


def main():
    rows = []
    for c in load_cases():
        culprit = c["story"]["solution"]["culprit"]
        alibi = next((s["alibi"] for s in c["story"]["suspects"] if s["name"] == culprit), "")
        ctx = f"FACT: {c['fact']}\nQUOTE: {c['quote']}\nDATE SCOPE: {c['scope']}\nSETUP: {c['story'].get('setup')}\n" \
              f"SUSPECT: {culprit}\nALIBI: {alibi}"
        d_raw, s1 = chat(DEFENSE, ctx)
        d = js(d_raw) or {"parse": d_raw[:300]}
        j_raw, s2 = chat(JUDGE, ctx + f"\nDEFENSE: {json.dumps(d, ensure_ascii=False)}")
        j = js(j_raw) or {"parse": j_raw[:300]}
        label, why = LABELS.get(c["id"], (None, ""))
        pred = j.get("strictly_impossible") if isinstance(j, dict) else None
        rows.append({"id": c["id"], "alibi": alibi, "defense": d, "judge": j, "label": label, "label_why": why,
                     "correct": pred == label, "sec": [s1, s2]})
        print(f"\n[{c['id']}] label={label} pred={pred} correct={pred == label} ({s1}s+{s2}s)\n  alibi={alibi}"
              f"\n  defense={d}\n  judge={j}", flush=True)
    acc = sum(r["correct"] for r in rows) / len(rows) if rows else 0
    print(f"\nACCURACY {sum(r['correct'] for r in rows)}/{len(rows)} = {acc:.2f}", flush=True)
    (OUT / "defense.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
