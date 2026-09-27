"""The review panel: several open models read the same code independently."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from polyjury.llm import chat, parse_json

# Measured 2026-09-16 on our own code: these two answer fast and return valid JSON.
# GLM-5.3 returned an empty body and Kimi-K3 timed out, so they are off by default.
# 2026-09-27: Nebius retired Qwen3.5-397B (404). Qwen3-235B-2507 replaced it: 5 valid findings
# in 10 s on fastapi-cli, where Kimi-K2.7-Code and MiniMax-M3 returned empty bodies.
REVIEWERS = [
    "deepseek-ai/DeepSeek-V4-Pro",
    "Qwen/Qwen3-235B-A22B-Instruct-2507",
    "openai/gpt-oss-120b",
]
TIMEOUT = 90.0

REVIEW_PROMPT = """You review code that an AI assistant wrote for someone who is not a professional developer and is about to publish it on the public internet.

Report only REAL defects that a user or an attacker would actually hit:
security holes, leaked secrets, crashes, wrong logic, money/quota drain, data loss.
Never report style, naming, typing or "consider adding tests".

For each defect:
- file: exact path from the FILE markers
- where: the function or the line content it happens in
- severity: high | med | low
- what_breaks: what the user sees or loses, in one plain sentence
- how_to_reproduce: the concrete action that triggers it (a request, an input, a sequence)

Answer with JSON only: {"findings":[{"file":str,"where":str,"severity":str,"what_breaks":str,"how_to_reproduce":str}]}
At most 6 findings, the most serious first."""

REPAIR_PROMPT = """Convert the code review below into JSON only:
{"findings":[{"file":str,"where":str,"severity":str,"what_breaks":str,"how_to_reproduce":str}]}
Keep at most 6 of the most serious. Do not invent anything that is not in the text."""


@dataclass
class Review:
    model: str
    findings: list[dict] = field(default_factory=list)
    seconds: float = 0.0
    repaired: bool = False
    error: str = ""


# Notes about the proof sandbox are for the chair. Jurors who read "the repository does not
# include the font" spent every finding on it, so they get the code alone.
SANDBOX_NOTES = ("### SYSTEM TOOLS", "### FONTS", "### ALSO PRESENT", "### ROBOT SIMULATION")


def code_only(bundle: str) -> str:
    lines = bundle.split("\n")
    return "\n".join(ln for ln in lines if not ln.startswith(SANDBOX_NOTES)).lstrip()


def _one(model: str, bundle: str) -> Review:
    try:
        raw, sec = chat(REVIEW_PROMPT, code_only(bundle), think=None, model=model,
                        max_tokens=8000, temperature=0, timeout=TIMEOUT)
    except Exception as exc:  # noqa: BLE001
        return Review(model=model, error=f"{type(exc).__name__}: {exc}"[:200])

    data = parse_json(raw)
    repaired = False
    if not (isinstance(data, dict) and data.get("findings")):
        if not raw.strip():
            return Review(model=model, seconds=sec, error="empty response")
        try:  # the model answered in prose: let the chair model normalise it
            fixed, sec2 = chat(REPAIR_PROMPT, raw[:30000], think=False,
                               max_tokens=4000, temperature=0, timeout=TIMEOUT)
            data, sec, repaired = parse_json(fixed), sec + sec2, True
        except Exception as exc:  # noqa: BLE001
            return Review(model=model, seconds=sec, error=f"repair failed: {exc}"[:200])

    findings = (data or {}).get("findings", []) if isinstance(data, dict) else []
    clean = []
    for f in findings[:6]:
        if isinstance(f, dict) and f.get("what_breaks"):
            f["model"] = model
            clean.append(f)
    return Review(model=model, findings=clean, seconds=sec, repaired=repaired)


def _one_with_retry(model: str, bundle: str) -> Review:
    """Measured 2026-09-27: DeepSeek and Qwen each came back empty once in four runs, then
    answered normally on the next call. One more try beats a panel of two."""
    first = _one(model, bundle)
    if first.findings or (first.error and "empty" not in first.error and not first.repaired):
        return first
    second = _one(model, bundle)
    second.seconds = round(first.seconds + second.seconds, 2)
    return second if second.findings else first


def review(bundle: str, models: list[str] | None = None) -> list[Review]:
    """Run every reviewer at the same time on the same code."""
    models = models or REVIEWERS
    with ThreadPoolExecutor(max_workers=len(models)) as pool:
        return list(pool.map(lambda m: _one_with_retry(m, bundle), models))


def summarise(reviews: list[Review]) -> dict:
    ok = [r for r in reviews if r.findings]
    return {
        "models_asked": len(reviews),
        "models_usable": len(ok),
        "findings_total": sum(len(r.findings) for r in ok),
        "per_model": {r.model: {"findings": len(r.findings), "seconds": r.seconds,
                                "repaired": r.repaired, "error": r.error} for r in reviews},
    }


def all_findings(reviews: list[Review]) -> list[dict]:
    out = []
    for r in reviews:
        out.extend(r.findings)
    return out
