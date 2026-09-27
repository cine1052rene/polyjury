"""One proof is one opinion. The same claim, proved by independently written scripts, has to
come out the same way before Polyjury reports it.

Off by default (POLYJURY_PROOFS=1). Measured 2026-09-28 on fastapi-cli, the same 8 claims proved
twice each way: one proof per claim gave the same verdict both times for 4/8 claims, three proofs
with this consensus also 4/8, and CONFIRMED flipped on 3/8 claims either way; the slowest claim
went from 92 s to 361 s, past the 300 s a serverless call gets. The swing comes from claims that
can be read more than one way, not from the luck of one script. What does keep a verdict honest
is the fix loop's control run: the same script, on the untouched code, must reproduce again.
"""
from __future__ import annotations

import os
from collections import Counter

PROOFS = max(1, int(os.environ.get("POLYJURY_PROOFS", "1")))
# the first proof keeps the chair's usual temperature; the others are allowed to differ
TEMPERATURES = [0.1, 0.4, 0.4, 0.6, 0.6]
KEEP = 1800  # characters of evidence kept per attempt


def temperature(i: int) -> float:
    return TEMPERATURES[min(i, len(TEMPERATURES) - 1)]


def decide(verdicts: list[str]) -> str:
    """REPRODUCED or NOT_REPRODUCED only with a majority and no dissent between the two."""
    n = Counter(verdicts)
    need = len(verdicts) // 2 + 1
    if n["REPRODUCED"] >= need and not n["NOT_REPRODUCED"]:
        return "REPRODUCED"
    if n["NOT_REPRODUCED"] >= need and not n["REPRODUCED"]:
        return "NOT_REPRODUCED"
    return "UNVERIFIED"


def tally(verdicts: list[str]) -> str:
    n = Counter(verdicts)
    parts = [f"{n[k]} {label}" for k, label in (("REPRODUCED", "reproduced"),
             ("NOT_REPRODUCED", "not reproduced"), ("UNVERIFIED", "inconclusive")) if n[k]]
    return ", ".join(parts)


def combine(claim, attempts: list):
    """Fold the attempts into one claim: the verdict they agree on, shown with the evidence of
    an attempt that reached it, and every attempt kept for anyone who wants to check."""
    verdicts = [a.verdict for a in attempts]
    verdict = decide(verdicts)
    if len(attempts) == 1:
        return attempts[0]
    # show an attempt that reached the verdict; on a split, the one that reproduced it,
    # because that is the evidence a human has to look at
    lead_verdict = verdict if verdict != "UNVERIFIED" or "REPRODUCED" not in verdicts else "REPRODUCED"
    lead = next((a for a in attempts if a.verdict == lead_verdict), attempts[0])
    note = f"[polyjury] {len(attempts)} independent proofs: {tally(verdicts)}."
    if verdict == "UNVERIFIED" and len(set(verdicts)) > 1:
        note += " They do not agree, so this is left to a human."
    for field in ("script", "what_it_proves", "proof_kind", "runner"):
        setattr(claim, field, getattr(lead, field))
    claim.verdict = verdict
    claim.evidence = (lead.evidence or "").rstrip() + "\n" + note
    claim.attempts = [{"verdict": a.verdict, "proof_kind": a.proof_kind, "what_it_proves": a.what_it_proves,
                       "evidence": (a.evidence or "")[-KEEP:], "script": a.script} for a in attempts]
    return claim
