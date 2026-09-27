"""Fix loop for code: Nemotron patches the file, and the proofs that reproduced the defect are run
again on the patched copy. The fix counts only when every one of them now says NOT_REPRODUCED and
a review of the diff finds a real fix rather than a removed feature or a special case for the test.
"""
from __future__ import annotations

import difflib
import time
from concurrent.futures import ThreadPoolExecutor

from polyjury.chair import SCRIPT_RE
from polyjury.llm import chat

MAX_ROUNDS = 2
MAX_FILE = 60_000          # characters: larger files are left to a human
BUDGET = 200               # seconds; a serverless call gets 300

PATCH_PROMPT = """You fix one defect in one file. You are given the claim, the proof script that
made the defect happen, what it printed, and the file. Change as little as possible. Keep every
feature working: do not delete the code path, do not special-case the proof's inputs, do not
catch-and-ignore the error. Return the COMPLETE new content of the file in one code block and
nothing else."""

RETRY_NOTE = """Your previous version did not fix it. The proofs were run again on it and printed:

{output}

Return the complete corrected file again, in one code block."""

REVIEW_PROMPT = """A file was patched to fix a defect, and the proof no longer reproduces it.
Read the diff. Is it a genuine fix of the defect described? It is NOT genuine if it removes or
disables the feature, special-cases the test's inputs, swallows the error, or only changes what
gets printed. Answer with one line: GENUINE, or NOT GENUINE: <why, briefly>."""


def _ask(claim, text: str, feedback: str) -> str:
    task = (f"CLAIM: {claim.title}\nWHAT BREAKS: {claim.what_breaks}\nFILE: {claim.file}\n\n"
            f"PROOF SCRIPT:\n{claim.script}\n\nWHAT IT PRINTED:\n{claim.evidence[-2500:]}\n\n"
            f"CURRENT FILE:\n{text}")
    if feedback:
        task += "\n\n" + RETRY_NOTE.format(output=feedback[-3000:])
    raw, _ = chat(PATCH_PROMPT, task, think=True, max_tokens=16000, temperature=0.1, timeout=150)
    blocks = SCRIPT_RE.findall(raw or "")
    return max(blocks, key=len).strip() + "\n" if blocks else ""


def _review(claim, diff: str) -> str:
    """'' when the diff is a genuine fix, else why not."""
    try:
        raw, _ = chat(REVIEW_PROMPT, f"CLAIM: {claim.title}\nWHAT BREAKS: {claim.what_breaks}\n\nDIFF:\n{diff[:20000]}",
                      think=True, max_tokens=4000, temperature=0, timeout=90)
    except Exception:  # noqa: BLE001
        return "the review of the diff could not run"
    lines = [ln.strip() for ln in (raw or "").splitlines() if ln.strip().upper().startswith(("GENUINE", "NOT GENUINE"))]
    line = lines[-1] if lines else "NOT GENUINE: no answer"
    return "" if line.upper().startswith("GENUINE") else (line.split(":", 1)[1].strip() if ":" in line else line)


def proofs_of(claim) -> list[str]:
    """Every script that reproduced the defect: the fix has to beat all of them."""
    scripts = [a["script"] for a in (claim.attempts or []) if a.get("verdict") == "REPRODUCED" and a.get("script")]
    return scripts or [claim.script]


def run(claim, repo, backend) -> dict:
    started = time.time()
    rel = claim.file.replace("\\", "/")
    path = repo.root / rel
    if not rel or not path.is_file():
        return {"kind": "code", "file": rel, "fixed": False, "rounds": [], "diff": "",
                "why": "the claim does not name a file in this repository"}
    original = path.read_text(encoding="utf-8", errors="replace")
    if len(original) > MAX_FILE:
        return {"kind": "code", "file": rel, "fixed": False, "rounds": [], "diff": "",
                "why": f"{rel} is {len(original)} characters; patches that large are left to a human"}
    scripts, rounds, feedback, text, why = proofs_of(claim), [], "", original, ""
    # control run: the same script on the untouched code has to reproduce again, or there is
    # nothing a patch could be shown to fix
    control = backend.run(scripts[0])
    if control.verdict != "REPRODUCED":
        return {"kind": "code", "file": rel, "fixed": False, "rounds": [], "diff": "",
                "control": control.verdict, "control_evidence": control.output[-1500:],
                "why": "run again on the untouched code, the proof did not reproduce the defect; "
                       "a fix could not be told apart from luck"}
    for n in range(1, MAX_ROUNDS + 1):
        if time.time() - started > BUDGET:
            break
        try:
            text = _ask(claim, original, feedback)
        except Exception as exc:  # noqa: BLE001
            why = f"could not write a patch: {exc}"[:200]
            break
        if not text.strip() or text == original:
            why = "Nemotron returned no change"
            break
        with ThreadPoolExecutor(max_workers=len(scripts)) as pool:
            results = list(pool.map(lambda s: backend.run(s, overrides={rel: text.encode("utf-8")}), scripts))
        verdicts = [r.verdict for r in results]
        rounds.append({"round": n, "verdicts": verdicts, "evidence": [r.output[-1500:] for r in results]})
        if all(v == "NOT_REPRODUCED" for v in verdicts):
            break
        feedback = "\n---\n".join(r.output for r in results)
    diff = "".join(difflib.unified_diff(original.splitlines(True), text.splitlines(True), f"a/{rel}", f"b/{rel}", n=3))
    beaten = bool(rounds) and all(v == "NOT_REPRODUCED" for v in rounds[-1]["verdicts"])
    if beaten:
        why = _review(claim, diff)
    return {"kind": "code", "file": rel, "fixed": beaten and not why, "rounds": rounds,
            "proofs": len(scripts), "control": control.verdict, "diff": diff if rounds else "", "why": why}
