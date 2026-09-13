"""v2: 규정 적용범위(scope) 분리 → 특별규정 우선 해석. extract.json 재사용."""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
from core.nebius_client import get_client
OUT = Path(__file__).resolve().parents[1] / "scratch" / "airtravel"
d = json.loads((OUT / "extract.json").read_text(encoding="utf-8"))
raw = get_client().raw

def call(system, user, think, max_tokens=6000):
    t0 = time.time()
    r = raw.chat.completions.create(model=config.TEXT_MODEL, temperature=0.1, max_tokens=max_tokens,
        messages=[{"role":"system","content":system},{"role":"user","content":user}],
        extra_body={"chat_template_kwargs":{"enable_thinking":think}})
    return (r.choices[0].message.content or ""), round(time.time()-t0,1)

STAGE_A = """Extract battery rules from ONE airline source. For each rule output
{"carrier","source_url","rule_text_verbatim","scope":"MOBILITY_AID_INSTALLED|MOBILITY_AID_REMOVED|MOBILITY_AID_SPARE|GENERAL_PORTABLE_ELECTRONICS|GENERAL_POWER_BANK|OTHER","wh_limit","conditions"}.
rule_text_verbatim must be copied exactly from the text. Scope must reflect who the rule is written for:
rules under a heading about wheelchairs/mobility aids are MOBILITY_AID_*; power bank/portable electronics tables are GENERAL_*.
Output JSON: {"rules":[...]} only."""

STAGE_B = """You check whether a power-wheelchair traveler can fly. Input: scoped rule records per carrier.
Legal principle: a specific mobility-aid provision overrides general portable-electronics/power-bank limits
for the wheelchair's own batteries. Use ONLY MOBILITY_AID_* rules for wheelchair batteries; mention GENERAL_* only if
no mobility-aid rule exists for that carrier (then mark UNKNOWN). Each carrier's rules apply only to its own leg —
never cite one carrier's page for another carrier. Strictest applicable rule across legs governs.
Output JSON: {"verdict","per_leg":[{"leg","carrier","applied_rules":[{"rule_text_verbatim","source_url","check":"PASS|FAIL|UNKNOWN","why"}]}],
"binding_constraints":[],"todo_before_departure":[],"questions_for_airline":[]}"""

scoped = {}
for name in ("Korean Air","Lufthansa"):
    txt = "\n\n".join(f"<{p['url']}>\n{p['text'][:9000]}" for p in d[name]["pages"])
    out, s = call(STAGE_A, f"Carrier: {name}\n{txt}", think=False)
    scoped[name] = out
    print(f"== Stage A {name} ({s}s)\n{out[:2500]}\n", flush=True)
(OUT/"v2_scoped.json").write_text(json.dumps(scoped, ensure_ascii=False, indent=2), encoding="utf-8")
scenario = ("Traveler: power wheelchair, lithium-ion, ONE removable battery 280 Wh, ONE spare 150 Wh, no manufacturer certificate.\n"
    "Itinerary: Korean Air ICN->FRA, Lufthansa FRA->BCN, departs in 30h.\nSCOPED RULES:\n" + json.dumps(scoped, ensure_ascii=False))
for label, think in (("no_think",False),("think",True)):
    out, s = call(STAGE_B, scenario, think)
    (OUT/f"v2_{label}.txt").write_text(out, encoding="utf-8")
    print(f"== Stage B {label} ({s}s)\n{out[:3500]}\n", flush=True)
print("DONE")
