"""Fix loop for robot descriptions: tighten the joint limit the simulation proved unsafe, then run
the same simulation on the patched file. Repeat until it is clear or MAX_ROUNDS is spent.

The new limit is measured, not guessed: the bisected first-contact angle, minus MARGIN. Hull
contact comes before real mesh contact, so this errs on the safe side and costs a little travel,
which the result states in degrees.
"""
from __future__ import annotations

import difflib
import math
import re

from polyjury import robot

MARGIN = 0.02      # rad kept between the new limit and the first contact
MAX_ROUNDS = 3
LINE = re.compile(r"^\s+(\S+) = ([+-]?[\d.]+) rad \(limit ([+-]?[\d.]+)\.\.([+-]?[\d.]+)\): (\S+) hits (\S+), "
                  r".*?first contact at ([+-]?[\d.]+|None) rad, exact meshes (\{.*\})\s*$", re.M)


def defects(evidence: str) -> list[dict]:
    """The contacts the proof counted as real (the template prints 'real': False for hull-only)."""
    out = []
    for j, value, lo, hi, a, b, onset, exact in LINE.findall(evidence or ""):
        if "'real': False" in exact or onset == "None":
            continue
        out.append({"joint": j, "value": float(value), "lo": float(lo), "hi": float(hi),
                    "a": a, "b": b, "onset": float(onset)})
    return out


def new_limits(found: list[dict]) -> dict[str, tuple[float, float]]:
    """Per joint, the tightest safe (lo, hi) across every contact it caused."""
    limits: dict[str, tuple[float, float]] = {}
    for d in found:
        lo, hi = limits.get(d["joint"], (d["lo"], d["hi"]))
        if d["value"] > 0:
            hi = min(hi, round(d["onset"] - MARGIN, 4))
        else:
            lo = max(lo, round(d["onset"] + MARGIN, 4))
        limits[d["joint"]] = (lo, hi)
    return limits


def patch(text: str, limits: dict[str, tuple[float, float]]) -> tuple[str, list[str]]:
    """Rewrite the limits in URDF (<limit lower= upper=>) or MJCF (range="lo hi") text."""
    changed = []
    for joint, (lo, hi) in limits.items():
        name = re.escape(joint)
        urdf = re.compile(rf'(<joint\b[^>]*\bname="{name}".*?</joint>)', re.S)
        m = urdf.search(text)
        now = _limits_in(text, joint)
        if m:
            block = new = m.group(1)
            if now and abs(now[0] - lo) > 1e-6:
                new = re.sub(r'(<limit\b[^>]*?\blower=")[^"]*(")', rf"\g<1>{lo:.4f}\g<2>", new, count=1)
            if now and abs(now[1] - hi) > 1e-6:
                new = re.sub(r'(<limit\b[^>]*?\bupper=")[^"]*(")', rf"\g<1>{hi:.4f}\g<2>", new, count=1)
            if new != block:
                text = text.replace(block, new, 1)
                changed.append(joint)
            continue
        mjcf = re.compile(rf'(<joint\b[^>]*\bname="{name}"[^>]*\brange=")[^"]*(")')
        if mjcf.search(text):
            text = mjcf.sub(rf"\g<1>{lo:.4f} {hi:.4f}\g<2>", text, count=1)
            changed.append(joint)
    return text, changed


def run(claim, repo, backend) -> dict:
    """claim: the simulator's REPRODUCED claim. Returns the fix, every round, and the diff."""
    rel = claim.file.replace("\\", "/")
    original = text = (repo.root / rel).read_text(encoding="utf-8")
    script = robot.sim_script(repo.root, repo.files, rel)
    # control run: measure the untouched file here rather than trust evidence the client sent
    control = backend.run(script)
    if control.verdict != "REPRODUCED":
        return {"kind": "robot", "file": rel, "fixed": False, "rounds": [], "diff": "",
                "control": control.verdict, "why": "run again, the simulation found no collision to fix"}
    evidence, rounds, before = control.output, [], {}
    for n in range(1, MAX_ROUNDS + 1):
        found = defects(evidence)
        if not found:
            break
        limits = new_limits(found)
        for d in found:
            before.setdefault(d["joint"], (d["lo"], d["hi"]))
        text, changed = patch(text, limits)
        if not changed:
            rounds.append({"round": n, "limits": limits, "verdict": "UNVERIFIED",
                           "evidence": "could not find those joints' limits in the file"})
            break
        result = backend.run(script, overrides={rel: text.encode("utf-8")})
        evidence = result.output
        rounds.append({"round": n, "limits": {k: list(v) for k, v in limits.items()},
                       "verdict": result.verdict, "evidence": evidence[-2500:]})
        if result.verdict == "NOT_REPRODUCED":
            break
    final = rounds[-1]["verdict"] if rounds else "UNVERIFIED"
    after = {j: _limits_in(text, j) for j in before}
    cost = {j: round(math.degrees((before[j][1] - after[j][1]) + (after[j][0] - before[j][0])), 1)
            for j in before if after.get(j)}
    return {"kind": "robot", "file": rel, "fixed": final == "NOT_REPRODUCED", "rounds": rounds, "control": "REPRODUCED",
            "travel_lost_deg": cost,
            "diff": "".join(difflib.unified_diff(original.splitlines(True), text.splitlines(True),
                                                 f"a/{rel}", f"b/{rel}", n=2))}


def _limits_in(text: str, joint: str) -> tuple[float, float] | None:
    m = re.search(rf'<joint\b[^>]*\bname="{re.escape(joint)}".*?</joint>', text, re.S)
    if m:
        lo = re.search(r'<limit\b[^>]*\blower="([^"]+)"', m.group(0))
        hi = re.search(r'<limit\b[^>]*\bupper="([^"]+)"', m.group(0))
        if lo and hi:
            return float(lo.group(1)), float(hi.group(1))
    m = re.search(rf'<joint\b[^>]*\bname="{re.escape(joint)}"[^>]*\brange="([^"]+)"', text)
    if m:
        lo, hi = m.group(1).split()[:2]
        return float(lo), float(hi)
    return None
