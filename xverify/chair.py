"""NVIDIA Nemotron chairs the panel: it merges the findings, then writes the proof."""
from __future__ import annotations

import ast
import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from engine.llm import chat, parse_json

CHAIR_TIMEOUT = 240.0

MERGE_PROMPT = """You chair a code review panel. Several models reviewed the SAME code independently and may describe the same problem in different words, or be plain wrong.

Merge their findings:
- Put findings with the same root cause into one claim, and list every model that raised it.
- Findings about different instances of the same weakness (for example several in-memory
  dictionaries that are never evicted, or several endpoints missing the same check) are ONE claim.
- Drop anything vague, cosmetic, or impossible to check by running code.
- Rewrite each claim so a non-developer understands what they would lose.

JSON only:
{"claims":[{"title":str,"file":str,"where":str,"severity":"high"|"med"|"low",
 "what_breaks":str,"models":[str]}],"dropped":[str]}
At most 8 claims, most serious first."""

PROOF_PROMPT = """You must PROVE or DISPROVE one claim about a repository by running code. Guessing is not allowed.

Write a single self-contained Python 3 script that decides the claim.
Rules:
- It runs with the repository root as the working directory and on sys.path.
- Prefer EXERCISING the code: import the module and call it, or drive the web app in-process
  with its test client, and print the real values you got back. Reading source text is only
  acceptable when the claim is purely about how the code is written.
- Standard library plus whatever the repository already imports. No network calls, no writes
  outside the working directory, no sleep longer than 2 seconds.
- Put the whole check inside try/except so it can never die without answering.
- The LAST line you print must be exactly "VERDICT: REPRODUCED" or "VERDICT: NOT_REPRODUCED".
  Print the evidence (values, status codes, matched lines) before it. If your own check errors
  out or the claim cannot be decided this way, print the error and then "VERDICT: NOT_REPRODUCED".

Reply in exactly this shape and nothing else:

PROVES: <one sentence: what the run will show>
KIND: dynamic | static
```python
<the full script>
```"""

SCRIPT_RE = re.compile(r"```(?:python)?\s*(.*?)```", re.S)
PROVES_RE = re.compile(r"PROVES:\s*(.+)")
KIND_RE = re.compile(r"KIND:\s*(dynamic|static)", re.I)


@dataclass
class Claim:
    title: str
    file: str = ""
    where: str = ""
    severity: str = "med"
    what_breaks: str = ""
    models: list[str] = field(default_factory=list)
    script: str = ""
    what_it_proves: str = ""
    proof_kind: str = ""
    verdict: str = "UNVERIFIED"     # REPRODUCED | NOT_REPRODUCED | UNVERIFIED
    evidence: str = ""
    runner: str = ""

    @property
    def agreed(self) -> bool:
        return len(set(self.models)) >= 2


def merge(findings: list[dict]) -> tuple[list[Claim], list[str]]:
    raw, _ = chat(MERGE_PROMPT, json.dumps(findings, ensure_ascii=False)[:80000],
                  think=True, max_tokens=8000, temperature=0, timeout=CHAIR_TIMEOUT)
    data = parse_json(raw) or {}
    claims = []
    for c in data.get("claims", [])[:8]:
        if isinstance(c, dict) and c.get("title"):
            claims.append(Claim(title=c["title"], file=c.get("file", ""), where=c.get("where", ""),
                                severity=c.get("severity", "med"), what_breaks=c.get("what_breaks", ""),
                                models=list(c.get("models", []))))
    return claims, list(data.get("dropped", []))


def _write_proof(claim: Claim, context: str) -> Claim:
    task = (f"CLAIM: {claim.title}\nFILE: {claim.file}\nWHERE: {claim.where}\n"
            f"WHAT BREAKS: {claim.what_breaks}\n\nREPOSITORY CODE:\n{context}")
    try:
        raw, _ = chat(PROOF_PROMPT, task[:90000], think=True, max_tokens=9000,
                      temperature=0.1, timeout=CHAIR_TIMEOUT)
        block = SCRIPT_RE.search(raw)
        claim.script = block.group(1).strip() if block else ""
        proves = PROVES_RE.search(raw)
        claim.what_it_proves = proves.group(1).strip() if proves else ""
        kind = KIND_RE.search(raw)
        claim.proof_kind = kind.group(1).lower() if kind else ""
        if not claim.script:
            claim.evidence = "the chair did not produce a script"
        else:
            claim.script = _make_it_parse(claim.script, task)
    except Exception as exc:  # noqa: BLE001
        claim.evidence = f"could not write a proof: {exc}"[:200]
    return claim


FIX_PROMPT = """Your Python script does not compile. Here is the interpreter error.
Return the corrected full script and nothing else, in one ```python code block.
Keep the same checks and the same final "VERDICT: ..." line."""


def _make_it_parse(script: str, task: str, tries: int = 2) -> str:
    """A proof that cannot even be parsed proves nothing, so repair it before running."""
    for _ in range(tries):
        try:
            ast.parse(script)
            return script
        except SyntaxError as err:
            detail = err.msg + " (line " + str(err.lineno) + ")" + chr(10) * 2 + script
            try:
                raw, _ = chat(FIX_PROMPT, detail[:60000], think=False, max_tokens=9000,
                              temperature=0, timeout=CHAIR_TIMEOUT)
            except Exception:  # noqa: BLE001
                return script
            block = SCRIPT_RE.search(raw)
            if not block:
                return script
            script = block.group(1).strip()
    return script


def write_proofs(claims: list[Claim], context: str, workers: int = 4) -> list[Claim]:
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda c: _write_proof(c, context), claims))
