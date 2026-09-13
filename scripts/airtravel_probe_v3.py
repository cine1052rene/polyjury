"""v3: 앞부분 자르기 대신 키워드 주변 구간을 모아 전달(휠체어 절 누락 방지)."""
import json, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
from core.nebius_client import get_client
OUT = Path(__file__).resolve().parents[1] / "scratch" / "airtravel"
d = json.loads((OUT / "extract.json").read_text(encoding="utf-8"))
raw = get_client().raw
KW = re.compile(r"(?i)wheelchair|mobility|휠체어|輪椅|battery|lithium|Wh\b|電池")

def windows(text, pad=700, cap=9000):
    spans=[]
    for m in KW.finditer(text):
        a,b=max(0,m.start()-pad),min(len(text),m.end()+pad)
        if spans and a<=spans[-1][1]: spans[-1][1]=max(spans[-1][1],b)
        else: spans.append([a,b])
    # 휠체어/모빌리티 포함 구간 우선
    spans.sort(key=lambda s: 0 if re.search(r"(?i)wheelchair|mobility|휠체어|輪椅", text[s[0]:s[1]]) else 1)
    out,n=[],0
    for a,b in spans:
        if n>=cap: break
        seg=text[a:b][:cap-n]; out.append(seg); n+=len(seg)
    return "\n[...]\n".join(out)

SYSTEM = """You check whether a power-wheelchair traveler can fly, using ONLY the source excerpts.
1) First classify each relevant rule's scope: MOBILITY_AID (written for wheelchairs/mobility aids and their batteries/spares)
   vs GENERAL (power banks, portable electronics). A specific mobility-aid provision overrides general limits for the
   wheelchair's own batteries. If a carrier has no mobility-aid rule in the excerpts, mark UNKNOWN (do not apply GENERAL).
2) Each carrier's page applies only to its own leg. Never cite one carrier's page for another.
3) The wheelchair's main battery is not a spare. Spares are additional batteries.
4) Quote rule text verbatim with source URL. Strictest applicable requirement across legs governs.
Output JSON: {"verdict":"OK|ACTION_NEEDED|LIKELY_REFUSED|UNKNOWN","per_leg":[{"leg","carrier","applied_rules":[{"scope","rule_text_verbatim","source_url","check":"PASS|FAIL|ACTION|UNKNOWN","why"}]}],
"binding_constraints":[],"todo_before_departure":[],"questions_for_airline":[]}"""
ex=[]
for name in ("Korean Air","Lufthansa"):
    for p in d[name]["pages"]:
        ex.append(f"### {name} <{p['url']}>\n{windows(p['text'])}")
scenario=("Traveler: power wheelchair, lithium-ion, ONE removable battery 280 Wh, ONE spare 150 Wh, no manufacturer certificate.\n"
 "Itinerary: Korean Air ICN->FRA, then Lufthansa FRA->BCN, departs in 30h.\n\nSOURCE EXCERPTS:\n"+"\n\n".join(ex))
print("korean air wheelchair section present:", "Battery regulations for electric wheelchairs" in scenario, flush=True)
for label,think in (("no_think",False),("think",True)):
    t0=time.time()
    r=raw.chat.completions.create(model=config.TEXT_MODEL,temperature=0.1,max_tokens=7000,
        messages=[{"role":"system","content":SYSTEM},{"role":"user","content":scenario}],
        extra_body={"chat_template_kwargs":{"enable_thinking":think}})
    c=r.choices[0].message.content or ""
    (OUT/f"v3_{label}.txt").write_text(c,encoding="utf-8")
    print(f"== v3 {label} ({round(time.time()-t0,1)}s in={r.usage.prompt_tokens} out={r.usage.completion_tokens})\n{c[:4500]}\n",flush=True)
print("DONE")
