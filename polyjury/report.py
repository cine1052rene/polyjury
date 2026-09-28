"""Turn verified claims into something a non-developer can act on."""
from __future__ import annotations

from polyjury.chair import Claim

MARK = {"REPRODUCED": "CONFIRMED", "NOT_REPRODUCED": "FALSE ALARM", "UNVERIFIED": "NEEDS A HUMAN"}


def label(claim) -> str:
    """A claim checked by reading the source is not the same as one that was run."""
    if claim.verdict != "REPRODUCED":
        return MARK.get(claim.verdict, claim.verdict)
    return "CONFIRMED — ran it" if claim.proof_kind == "dynamic" else "LIKELY — read the code"


def upstream_line(claim) -> str:
    """One line on what the repository's own tracker already says about a reproduced defect."""
    k = getattr(claim, "known", None) or {}
    if not k or claim.verdict != "REPRODUCED":
        return ""
    ref = k.get("ref") or {}
    tag = f"{'PR' if ref.get('kind') == 'pull' else 'issue'} #{ref.get('number')} ({ref.get('state')})" if ref.get("number") else ref.get("url", "")
    if k.get("status") == "known":
        return f"already reported upstream: {tag} — {k.get('why', '')}".rstrip(" —")
    if k.get("status") == "fixed":
        return f"already addressed upstream: {tag} — {k.get('why', '')}".rstrip(" —")
    if k.get("status") == "elsewhere":
        return f"not in this repository's tracker, but described elsewhere: {ref.get('url', '')} — {k.get('why', '')}".rstrip(" —")
    if k.get("status") == "new":
        return "not found in the repository's issues or pull requests — worth reporting"
    return f"upstream check did not complete ({k.get('error') or 'search failed'})"


def text_report(repo_name: str, claims: list[Claim], panel: dict) -> str:
    confirmed = [c for c in claims if c.verdict == "REPRODUCED"]
    refuted = [c for c in claims if c.verdict == "NOT_REPRODUCED"]
    unknown = [c for c in claims if c.verdict == "UNVERIFIED"]
    lines = [
        f"# Cross-verification report — {repo_name}",
        "",
        f"{panel['models_usable']} of {panel['models_asked']} reviewers answered, "
        f"{panel['findings_total']} raw findings -> {len(claims)} claims -> "
        f"**{len(confirmed)} proved by running code**.",
        "",
    ]
    ran = [c for c in confirmed if c.proof_kind == "dynamic"]
    lines[2] = lines[2].replace(f"**{len(confirmed)} proved by running code**",
                                f"**{len(ran)} reproduced by running code**, {len(confirmed) - len(ran)} supported by reading it")
    for title, group in (("Confirmed — fix these", confirmed),
                         ("False alarms — the panel was wrong", refuted),
                         ("Could not be decided by running code", unknown)):
        if not group:
            continue
        lines += [f"## {title}", ""]
        for c in group:
            votes = f"{len(set(c.models))} of {panel['models_asked']} reviewers"
            lines += [f"### [{c.severity.upper()}] {c.title}",
                      f"- What breaks: {c.what_breaks}",
                      f"- Where: `{c.file}` — {c.where}",
                      f"- Raised by: {votes} ({', '.join(sorted(set(c.models))) or 'n/a'})",
                      f"- Proof ({c.proof_kind or 'n/a'}): {c.what_it_proves or 'n/a'} — ran in {c.runner}"]
            if upstream_line(c):
                lines.append(f"- Upstream: {upstream_line(c)}")
            lines += ["```", c.evidence.strip()[:900] or "(no output)", "```", ""]
    return "\n".join(lines)


def fix_prompt(claims: list[Claim]) -> str:
    """A prompt the user can paste back into the assistant that wrote the code."""
    confirmed = [c for c in claims if c.verdict == "REPRODUCED"]
    if not confirmed:
        return ""
    out = ["Fix these defects in my code. Each one was reproduced by running a script, "
           "so do not argue that it cannot happen. Keep the behaviour of everything else.", ""]
    for i, c in enumerate(confirmed, 1):
        out += [f"{i}. {c.title}",
                f"   file: {c.file} ({c.where})",
                f"   impact: {c.what_breaks}",
                f"   proof: {c.what_it_proves}"]
        if (c.known or {}).get("status") in ("known", "fixed") and (c.known.get("ref") or {}).get("url"):
            out.append(f"   upstream: {c.known['ref']['url']} already covers this — read it before changing anything")
        out.append("")
    out.append("After each fix, tell me in one line how I can check it myself.")
    return "\n".join(out)
