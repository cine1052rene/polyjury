"""Grade an accusation: right suspect? evidence that really breaks the alibi? a sound investigation process?"""
from __future__ import annotations

from urllib.parse import urlparse

from engine.llm import chat, parse_json

EVIDENCE_PROMPT = """You are the JUDGE in a fair-play detective game. A player accuses a suspect and submits evidence found on the web.
Decide whether the EVIDENCE, read reasonably, makes the ACCUSED SUSPECT'S ALIBI strictly impossible.
If any reasonable reading keeps the alibi possible, or the evidence concerns a different place, date or service, answer false.
Output ONLY JSON {"supports_accusation": true|false, "reason": str}  (reason: max 40 words, addressed to the player)"""


def _domain(url: str) -> str:
    return urlparse(url or "").netloc.removeprefix("www.")


def check_evidence(setup: str, alibi: str, evidence: dict) -> dict:
    text = (f"CASE SETUP (gives the date and time of the theft): {setup}\n"
            f"ACCUSED SUSPECT'S ALIBI (for that date and time): {alibi}\n"
            f"EVIDENCE TITLE: {evidence.get('title', '')}\n"
            f"EVIDENCE PUBLISHED: {evidence.get('published') or 'unknown'}\nEVIDENCE URL: {evidence.get('url', '')}\n"
            f"EVIDENCE TEXT: {evidence.get('snippet', '')[:1500]}")
    total = 0.0
    for max_tokens in (4000, 8000):  # retry once with more room if the reasoning ate the answer
        raw, sec = chat(EVIDENCE_PROMPT, text, think=True, max_tokens=max_tokens, temperature=0)
        total += sec
        verdict = parse_json(raw)
        if isinstance(verdict, dict) and isinstance(verdict.get("supports_accusation"), bool):
            return {"supports_accusation": verdict["supports_accusation"],
                    "reason": str(verdict.get("reason", ""))[:300], "sec": round(total, 2)}
    return {"supports_accusation": False, "reason": "The court could not reach a verdict on this evidence.", "sec": round(total, 2)}


def grade(case: dict, suspect_id: str, evidence: dict | None, process: dict) -> dict:
    public, hidden = case["public"], case["hidden"]
    accused = next((s for s in public["suspects"] if s["id"] == suspect_id), None)
    if accused is None:
        raise ValueError("unknown suspect")
    correct = suspect_id == hidden["culprit_id"]

    evidence_check = None
    if evidence and evidence.get("url"):
        evidence_check = check_evidence(public["setup"], accused["alibi"], evidence)
    supports = bool(evidence_check and evidence_check["supports_accusation"])

    opened = [u for u in process.get("opened", []) if u]
    domains = {_domain(u) for u in opened} | ({_domain(evidence["url"])} if evidence and evidence.get("url") else set())
    domains.discard("")
    badges = [
        {"id": "stop", "earned": int(process.get("elapsed_sec", 0)) >= 45},
        {"id": "investigate", "earned": len(opened) >= 1},
        {"id": "coverage", "earned": len(domains) >= 2 or len(set(process.get("queries", []))) >= 2},
        {"id": "trace", "earned": bool(evidence and (_domain(evidence.get("url", "")) == hidden["domain"] or supports))},
    ]
    score = 40 * correct + 30 * supports + round(7.5 * sum(b["earned"] for b in badges))

    return {
        "correct": correct,
        "accused": accused,
        "evidence_check": evidence_check,
        "badges": badges,
        "score": score,
        "reveal": {
            "culprit_id": hidden["culprit_id"],
            "culprit": hidden["culprit"],
            "fact_en": hidden["fact_en"],
            "quote": hidden["quote"],
            "source_url": hidden["url"],
            "source_domain": hidden["domain"],
            "published": hidden.get("published"),
            "why_impossible": hidden["why_impossible"],
        },
    }
