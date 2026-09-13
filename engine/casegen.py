"""Write a fictional case around a real fact, then let the fair-play court accept or reject it."""
from __future__ import annotations

import datetime as dt
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import Callable

from engine.cities import City
from engine.facts import Fact
from engine.llm import NEMOTRON, chat, parse_json

Log = Callable[[str], None]

WRITER_PROMPT = """Write a SHORT fair-play whodunit in English for a daily detective game.
- Setting: {city}, on the fact's date. The crime is a non-violent theft. All people are fictional.
- Exactly 3 suspects. Exactly ONE suspect's alibi must be made STRICTLY IMPOSSIBLE by the FACT under a precise reading:
  match who/what the restriction applies to (if a road is closed to vehicles, that alibi must involve driving there;
  if no trains run on a segment, that alibi must be riding a train on that exact segment during that time).
- The other two alibis must involve completely different places in {city}, have nothing to do with the fact,
  and be ordinary and checkable (a receipt, a gym log, a ticket).
- Do NOT mention the fact, the closure or the restriction anywhere in the setup or alibis.
- The setup must state the date and the time window of the theft.
- Under 140 words in total. Names should feel natural for {city}.
{feedback}
Output ONLY JSON: {{"title":str,"setup":str,"suspects":[{{"name":str,"alibi":str}}],"solution":{{"culprit":str,"why_impossible":str}}}}"""

JUDGE_PROMPT = """You are the JUDGE of a fair-play mystery. Decide if the ALIBI is STRICTLY IMPOSSIBLE given the FACT text only.
If any reasonable reading consistent with the fact exists, it is NOT impossible.
Output ONLY JSON {"strictly_impossible": true|false, "reason": str}"""

NON_LATIN = re.compile(r"[Ѐ-ӿ぀-ヿ一-鿿가-힣]")


def _fact_context(fact: Fact) -> str:
    return (f"FACT: {fact.fact_en}\nORIGINAL QUOTE: {fact.quote}\nDATE SCOPE: {fact.date_scope}\n"
            f"PLACE: {fact.place}\nAPPLIES TO: {fact.applies_to}")


def judge_alibi(fact: Fact, alibi: str) -> dict:
    raw, sec = chat(JUDGE_PROMPT, f"{_fact_context(fact)}\nALIBI: {alibi}", think=True, max_tokens=4000, temperature=0)
    verdict = parse_json(raw)
    if not isinstance(verdict, dict) or not isinstance(verdict.get("strictly_impossible"), bool):
        return {"strictly_impossible": None, "reason": "judge reply unreadable", "sec": sec}
    return {"strictly_impossible": verdict["strictly_impossible"], "reason": str(verdict.get("reason", "")), "sec": sec}


def _valid_story(story: object) -> bool:
    if not isinstance(story, dict):
        return False
    suspects = story.get("suspects")
    return (isinstance(suspects, list) and len(suspects) == 3
            and all(isinstance(s, dict) and s.get("name") and s.get("alibi") for s in suspects)
            and isinstance(story.get("solution"), dict) and story["solution"].get("culprit")
            and story.get("title") and story.get("setup"))


def _script_problems(story: dict) -> list[str]:
    texts = [story["title"], story["setup"], story["solution"].get("why_impossible", "")]
    texts += [s["alibi"] for s in story["suspects"]]
    return ["non-English script in story text"] if any(NON_LATIN.search(t or "") for t in texts) else []


def generate_case(city: City, facts: list[Fact], today: dt.date, *, attempts_per_fact: int = 2,
                  log: Log = print) -> dict | None:
    for fact in facts:
        feedback = ""
        for attempt in range(1, attempts_per_fact + 1):
            raw, sec = chat(WRITER_PROMPT.format(city=city.name, feedback=feedback), _fact_context(fact),
                            think=True, max_tokens=5000, temperature=0.7)
            story = parse_json(raw)
            if not _valid_story(story):
                log(f"  writer attempt {attempt}: invalid output ({sec}s)")
                feedback = "Your previous output was not valid JSON with exactly 3 suspects."
                continue
            suspects = story["suspects"]
            with ThreadPoolExecutor(max_workers=3) as pool:
                verdicts = list(pool.map(lambda s: judge_alibi(fact, s["alibi"]), suspects))
            names = [s["name"] for s in suspects]
            culprit = story["solution"]["culprit"]
            idx = names.index(culprit) if culprit in names else None
            fair = (idx is not None and verdicts[idx]["strictly_impossible"] is True
                    and all(v["strictly_impossible"] is False for i, v in enumerate(verdicts) if i != idx))
            problems = _script_problems(story)
            log(f"  writer attempt {attempt} ({sec}s): culprit={culprit} fair={fair} problems={problems} "
                f"verdicts={[(n, v['strictly_impossible']) for n, v in zip(names, verdicts)]}")
            if fair and not problems:
                return _build_case(city, fact, story, verdicts, today, attempt)
            feedback = "PREVIOUS ATTEMPT REJECTED BY THE FAIR-PLAY JUDGE: " + "; ".join(
                f"{n}: impossible={v['strictly_impossible']} ({v['reason'][:180]})" for n, v in zip(names, verdicts))
            if problems:
                feedback += " Also: write every word in English."
    return None


def _build_case(city: City, fact: Fact, story: dict, verdicts: list[dict], today: dt.date, attempt: int) -> dict:
    ids = ["A", "B", "C"]
    suspects = [{"id": i, "name": s["name"], "alibi": s["alibi"]} for i, s in zip(ids, story["suspects"])]
    culprit = next(s for s in suspects if s["name"] == story["solution"]["culprit"])
    return {
        "id": f"{city.id}-{today.isoformat()}",
        "city": city.id,
        "city_name": city.name,
        "date": today.isoformat(),
        "public": {
            "title": story["title"],
            "setup": story["setup"],
            "suspects": suspects,
            "brief": f"One of these alibis collides with a real public fact in {city.name} this week. "
                     "Search the live web, pick your evidence, and name the thief.",
        },
        "hidden": {
            "culprit_id": culprit["id"],
            "culprit": culprit["name"],
            "why_impossible": story["solution"].get("why_impossible", ""),
            **asdict(fact),
        },
        "court": {
            "model": NEMOTRON,
            "writer_attempt": attempt,
            "verdicts": [{"suspect": s["id"], **v} for s, v in zip(suspects, verdicts)],
        },
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }
