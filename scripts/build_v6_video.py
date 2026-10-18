"""Demo video v6: the v5 story, shorter, with motion-graphic summaries (HyperFrames).

Every scene's length comes from its narration clip (private/press/narration-v6/n*.wav, voiced by
scripts/narrate_v6.py), so the picture never waits for the voice and the voice never runs over.
Footage is the same real recordings as v5, cropped to the left of the Sources drawer and sped up
where the models are thinking; the speed is always on screen. Writes the composition to
private/press/build-v6/hf/index.html and build-v6/timeline.json (for make_captions_v6.py).
Render: cd private/press/build-v6/hf && npx hyperframes render --output ../../polyjury-demo-v6.mp4
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

PRESS = Path(__file__).resolve().parents[1] / "private" / "press"
HF = PRESS / "build-v6" / "hf"
A = HF / "assets"
LEAD, TAIL = 0.25, 0.6


def dur(p: Path) -> float:
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                 "default=nw=1:nk=1", str(p)], capture_output=True, text=True).stdout)


CSS = """
:root { --bg:#0a0c11; --panel:#141926; --line:#232c3d; --ink:#e9edf5; --muted:#8b95ab; --accent:#76e3a1;
  --dim:#17301f; --warn:#f0c36d; --cold:#6f7d99; --mono:"JetBrains Mono", ui-monospace, monospace; }
* { margin:0; padding:0; box-sizing:border-box; }
html, body { width:1920px; height:1080px; overflow:hidden; background:var(--bg); }
#root { position:relative; width:100%; height:100%; overflow:hidden; font-family:Inter, system-ui, sans-serif; color:var(--ink); }
.bg { position:absolute; inset:0; background-image:linear-gradient(var(--line) 1px, transparent 1px),
  linear-gradient(90deg, var(--line) 1px, transparent 1px); background-size:80px 80px; opacity:.18; }
.glow { position:absolute; width:1500px; height:1500px; left:200px; top:-600px; border-radius:50%;
  background:radial-gradient(circle, rgba(118,227,161,.09), transparent 62%); }
.clip { position:absolute; inset:0; z-index:2; }
video { z-index:1; }
.pad { position:absolute; left:0; right:0; top:0; height:920px; padding:84px 110px 0; }
.kicker { font:700 22px var(--mono); letter-spacing:.26em; color:var(--accent); text-transform:uppercase; }
.title { font-size:84px; font-weight:800; letter-spacing:-.035em; margin-top:14px; line-height:1.04; }
.title em { font-style:normal; color:var(--accent); }
/* footage scenes: the recording on the left, the summary on the right */
.shot { position:absolute; left:56px; top:64px; width:1102px; height:864px; border-radius:16px; object-fit:cover; }
.shot.wide { height:620px; top:150px; }
.frame { position:absolute; left:52px; top:60px; width:1110px; height:872px; border-radius:20px;
  border:2px solid var(--line); box-shadow:0 30px 80px rgba(0,0,0,.55); }
.frame.wide { top:146px; height:628px; }
.side { position:absolute; left:1212px; right:70px; top:70px; }
.side .kicker { font-size:19px; }
.side h2 { font-size:50px; font-weight:800; letter-spacing:-.03em; line-height:1.08; margin-top:12px; }
.side ul { list-style:none; margin-top:30px; display:grid; gap:18px; }
.side li { font-size:28px; line-height:1.3; color:#c9d1e1; padding-left:30px; position:relative; }
.side li::before { content:""; position:absolute; left:0; top:13px; width:12px; height:12px; border-radius:3px; background:var(--accent); }
.side li b { color:var(--ink); }
.badge { position:absolute; left:84px; top:88px; font:700 22px var(--mono); color:#07140c; background:var(--accent);
  padding:8px 14px; border-radius:10px; }
.badge.live { background:var(--warn); }
.src { font:500 19px var(--mono); color:var(--cold); margin-top:22px; }
.stamp { display:inline-block; font:700 28px var(--mono); letter-spacing:.05em; border:3px solid var(--accent);
  color:var(--accent); background:var(--dim); border-radius:14px; padding:12px 20px; margin-top:30px; }
.stamp.warn { color:var(--warn); border-color:var(--warn); background:#2a2312; }
.big { font:800 64px Inter; letter-spacing:-.03em; color:var(--accent); margin-top:26px; }
.note { font-size:21px; color:var(--muted); margin-top:16px; line-height:1.4; }
/* flow cards */
.flow { display:flex; margin-top:60px; }
.node { width:372px; min-height:330px; background:var(--panel); border:2px solid var(--line); border-radius:22px;
  padding:34px 34px 30px; position:relative; }
.node .num { font:700 22px var(--mono); color:var(--muted); }
.node h3 { font-size:46px; font-weight:700; letter-spacing:-.02em; margin-top:10px; }
.node p { font-size:27px; color:var(--muted); margin-top:12px; line-height:1.35; }
.node .lit { position:absolute; inset:-2px; border-radius:22px; border:2px solid var(--accent);
  box-shadow:0 0 38px rgba(118,227,161,.35); opacity:0; }
.node.audit .lit { border-color:var(--warn); box-shadow:0 0 38px rgba(240,195,109,.3); }
.link { width:64px; align-self:center; height:4px; position:relative; }
.link .track { position:absolute; inset:0; background:var(--line); }
.link .fill { position:absolute; inset:0; background:var(--accent); transform-origin:left center; transform:scaleX(0); display:block; width:100%; }
.chips { display:flex; gap:8px; margin-top:16px; }
.chip { font:600 17px var(--mono); padding:6px 10px; border-radius:999px; border:1px solid var(--line); color:#bcc6d9;
  background:#10141e; white-space:nowrap; display:inline-block; }
.simnote { margin-top:40px; font-size:32px; color:#c9d1e1; }
.simnote b { color:var(--accent); }
/* numbers */
.row { display:flex; align-items:baseline; gap:30px; margin-top:70px; }
.stat b { font:800 150px Inter; letter-spacing:-.05em; display:inline-block; }
.stat span { display:block; font-size:34px; color:var(--muted); margin-top:-6px; }
.stat.win b { color:var(--accent); }
.arrow { font-size:70px; color:var(--cold); }
.refs { margin-top:44px; display:grid; gap:14px; font-size:30px; color:#c9d1e1; }
.refs b { color:var(--accent); }
/* screenshots */
.paper { position:absolute; width:880px; border-radius:14px; border:2px solid var(--line); box-shadow:0 30px 80px rgba(0,0,0,.6); }
/* title + outro */
.hero { font-size:150px; font-weight:800; letter-spacing:-.05em; }
.verbs { display:flex; gap:26px; margin-top:26px; flex-wrap:wrap; }
.verb { font-size:58px; font-weight:700; letter-spacing:-.03em; }
.verb.g { color:var(--accent); }
.sub { font:700 30px var(--mono); color:var(--muted); margin-top:40px; letter-spacing:.06em; }
.credits { margin-top:50px; display:grid; gap:20px; }
.cr { display:flex; gap:24px; align-items:baseline; font-size:36px; }
.cr i { font:700 22px var(--mono); font-style:normal; color:var(--accent); width:300px; letter-spacing:.14em; text-transform:uppercase; }
.cr span { color:var(--muted); font-size:26px; }
.url { font:800 72px Inter; color:var(--accent); margin-top:56px; letter-spacing:-.03em; }
.repo { font:500 26px var(--mono); color:var(--muted); margin-top:12px; }
.vs { display:flex; gap:40px; margin-top:44px; }
.col { flex:1; border-radius:24px; padding:40px 44px; border:2px solid var(--line); background:var(--panel); }
.col.win { border-color:var(--accent); box-shadow:0 0 50px rgba(118,227,161,.22); }
.lab { font:700 24px var(--mono); letter-spacing:.2em; text-transform:uppercase; color:var(--muted); }
.col.win .lab { color:var(--accent); }
.what { font-size:76px; font-weight:800; letter-spacing:-.035em; margin-top:14px; }
.col.dim .what { color:#9aa3b7; }
.sub2 { font-size:30px; color:var(--muted); margin-top:12px; }
.badges { display:flex; gap:28px; margin-top:46px; }
.bdg { flex:1; border-left:4px solid var(--accent); padding:4px 0 4px 22px; }
.bdg b { display:block; font-size:36px; letter-spacing:-.02em; }
.bdg span { display:block; font-size:25px; color:var(--muted); margin-top:6px; line-height:1.3; }
.badge.w { top:174px; }
"""


def side(kicker: str, title: str, items: list[str], extra: str = "", src: str = "") -> str:
    lis = "".join(f'<li class="it">{x}</li>' for x in items)
    return (f'<div class="side"><p class="kicker">{kicker}</p><h2>{title}</h2><ul>{lis}</ul>{extra}'
            f'{f"<p class=src>{src}</p>" if src else ""}</div>')


def build() -> None:
    n = {k: dur(A / f"{k}.wav") for k in [f"n{i}" for i in range(10)]}
    clip = {k: dur(A / f"{k}.mp4") for k in ("arm", "m_a", "m_b", "m_up", "m_fix1", "m_fix2", "c_a", "c_b", "t_a", "t_b", "t_c")}
    need = lambda k: LEAD + n[k] + TAIL  # noqa: E731
    lens = {
        "s0": max(need("n0"), clip["arm"] + 3.0), "s1": need("n1"), "s2": need("n2"),
        "s3": max(need("n3"), clip["m_a"] + clip["m_b"]), "s4": need("n4"),
        "s5": max(need("n5"), clip["m_fix1"] + clip["m_fix2"]), "s6": max(need("n6"), clip["c_a"] + clip["c_b"]),
        "s7": need("n7"), "s8": max(need("n8"), clip["t_a"] + clip["t_b"] + clip["t_c"]), "s9": need("n9") + 0.6,
    }
    t, at = 0.0, {}
    for k, v in lens.items():
        at[k] = round(t, 3)
        t += v
    total = round(t, 2)
    S = lambda k: at[k]  # noqa: E731
    L = lambda k: round(lens[k], 3)  # noqa: E731

    def video(id_: str, src: str, start: float, cls: str = "shot") -> str:
        return (f'<video id="{id_}" class="{cls}" src="assets/{src}.mp4" muted playsinline '
                f'data-start="{round(start, 3)}" data-duration="{round(clip[src], 3)}" data-track-index="1"></video>')

    def scene(k: str, body: str) -> str:
        return f'<section id="{k}" class="clip" data-start="{S(k)}" data-duration="{L(k)}" data-track-index="2">{body}</section>'

    up_card = S("s4") + clip["m_up"]
    html: list[str] = [
        scene("s0", '<div class="frame wide"></div>'
              '<img class="paper" id="h332" src="assets/pr332.png" style="left:110px;top:150px;width:1000px">' + side(
                  "Found by Polyjury", "A bug in DeepMind's robot arm model",
                  ["MuJoCo Menagerie, SO-101: the elbow drives the gripper into the shoulder, inside its own joint limits",
                   "render: the same elbow in the arm maker's own URDF (SO-ARM100)"],
                  '<div id="h0"><p class="note" style="font-size:28px;color:#c9d1e1;margin-top:28px">'
                  '<b style="color:var(--accent)">Issue #325</b> — reported by me, 28 Sep</p>'
                  '<p class="note" style="font-size:28px;color:#c9d1e1"><b style="color:var(--accent)">PR #332</b> — '
                  'someone else\'s fix, open (17 Oct)</p></div>')),
        scene("s1", '<div class="pad"><p class="kicker">Why it is different</p><div class="vs">'
              '<div class="col dim" id="d1"><p class="lab">A typical AI review</p><p class="what">“This might be wrong.”</p>'
              '<p class="sub2">an opinion: you check it yourself</p></div>'
              '<div class="col win" id="d2"><p class="lab">Polyjury</p><p class="what">A proof that ran.</p>'
              '<p class="sub2">confirmed only when it reproduces</p></div></div><div class="badges">'
              '<div class="bdg"><b>Proof by execution</b><span>every claim runs in a Nebius Sandbox microVM</span></div>'
              '<div class="bdg"><b>Robots by simulation</b><span>MuJoCo measures what jurors cannot read</span></div>'
              '<div class="bdg"><b>Checks upstream first</b><span>issues, pull requests and the web, before you report</span></div>'
              '</div></div>'),
        scene("s2", '<div class="pad"><p class="kicker">How a verdict is reached</p>'
              '<h1 class="title">Every claim has to <em>prove itself.</em></h1><div class="flow">'
              '<div class="node" id="f1"><div class="lit"></div><p class="num">01</p><h3>Three jurors</h3>'
              '<p>read the code separately, on Nebius Token Factory</p><div class="chips">'
              '<span class="chip c">DeepSeek</span><span class="chip c">Qwen3</span><span class="chip c">gpt-oss</span></div></div>'
              '<div class="link"><span class="track"></span><span class="fill" id="k1"></span></div>'
              '<div class="node" id="f2"><div class="lit"></div><p class="num">02</p><h3>Nemotron presides</h3>'
              '<p>merges the claims and writes a proof for each one</p></div>'
              '<div class="link"><span class="track"></span><span class="fill" id="k2"></span></div>'
              '<div class="node" id="f3"><div class="lit"></div><p class="num">03</p><h3>It runs</h3>'
              '<p>every proof in its own Nebius Sandbox microVM</p></div>'
              '<div class="link"><span class="track"></span><span class="fill" id="k3"></span></div>'
              '<div class="node audit" id="f4"><div class="lit"></div><p class="num">04</p><h3>The audit</h3>'
              '<p>Nemotron throws out any verdict its own output doesn\'t support</p></div></div>'
              '<p class="simnote" id="sim">Robot model? <b>Polyjury itself adds a simulation claim</b> — jurors only read text.</p></div>'),
        scene("s3", '<div class="frame"></div><span class="badge" id="b3a">4× speed</span>'
              '<span class="badge" id="b3b">12× speed</span>' + side(
                  "Live site · recorded 11 Oct", "DeepMind's MuJoCo Menagerie, SO-101",
                  ["<b>3 jurors</b> → 10 findings", "<b>Nemotron</b> → 9 claims",
                   "each proved in its own <b>Nebius Sandbox</b>"],
                  '<div id="v3"><p class="big">1 reproduced</p><p class="note">by simulation: the elbow collision · '
                  '5 juror claims were false alarms</p><span class="stamp">CONFIRMED · RAN IT</span></div>')),
        scene("s4", '<div class="frame" id="f4frame"></div><span class="badge" id="b4">1× speed</span>'
              '<img class="paper" id="p332" src="assets/pr332.png" style="left:110px;top:90px;width:1000px">' + side(
                  "Already reported?", "Search before you report",
                  ["the repository's issues and pull requests, plus <b>Tavily</b> web search",
                   "<b>Nemotron</b> judges whether a hit is the same defect"],
                  '<div id="v4"><p class="note" style="font-size:26px;color:#c9d1e1;margin-top:26px">'
                  'found on the live run: <b style="color:var(--accent)">PR #332</b>, another contributor\'s '
                  '“Fixes #325”. Open, not merged (17 Oct)</p></div>')),
        scene("s5", '<div class="frame"></div><span class="badge" id="b5a">10× speed</span>'
              '<span class="badge" id="b5b">1× speed</span>' + side(
                  "Fix it, then prove the fix", "Same sealed proof, patched file",
                  ["runs on the untouched file first — it must reproduce", "then on the patched copy"],
                  '<div id="v5"><p class="big" style="font-size:52px">elbow_flex 1.69 → 1.5594</p>'
                  '<span class="stamp">NOT_REPRODUCED</span><p class="note">cost: 7.5° of travel · contacts under 3 mm '
                  'are ignored; PR #332 chose a stricter 1.45 rad</p></div>')),
        scene("s6", '<div class="frame"></div><span class="badge" id="b6a">20× speed</span>'
              '<span class="badge" id="b6b">1× speed</span>' + side(
                  "Ordinary code · recorded 27 Sep", "fastapi-cli, the same way",
                  ["each proof in a sandbox, after trying to install the declared dependencies",
                   "<b>Nemotron</b> audits every run"],
                  '<div id="v6"><span class="stamp warn">THROWN OUT</span><p class="note">printed REPRODUCED — '
                  'and nothing that showed it happen</p></div>')),
        scene("s7", '<div class="pad"><p class="kicker">In the field</p><h1 class="title">Reproduced is not the same as <em>a bug.</em></h1>'
              '<div class="row"><div class="stat" id="t1"><b id="q1">0</b><span>public repositories</span></div>'
              '<div class="arrow a7">→</div><div class="stat" id="t2"><b id="q2">0</b><span>claims reproduced</span></div>'
              '<div class="arrow a7">→</div><div class="stat win" id="t3"><b id="q3">0</b><span>real defects, checked by hand</span></div>'
              '<span class="stamp warn" id="nah" style="margin-left:20px;align-self:center">NEEDS A HUMAN</span></div>'
              '<div class="refs" id="refs"><p>elbow self-collision → <b>issue #325</b>, filed by me</p>'
              '<p>wrist range mismatch → <b>PR #324</b>, someone else\'s — merged</p></div></div>'),
        scene("s8", '<div class="frame wide"></div><span class="badge w" id="b8a">2× speed</span>'
              '<span class="badge w" id="b8b">1× speed</span>' + side(
                  "Try it · the live site, 17 Oct", "polyjury.vercel.app",
                  ["<b>Recorded verdict</b>: a finished case, replayed", "<b>Sign in with GitHub</b>: optional, asks for no permissions",
                   "<b>Your own Nebius key</b>: instead of the demo credits", "<b>MCP server</b>: Claude Code or Codex can ask for a verdict"])),
        scene("s9", '<div class="pad" style="padding-top:110px"><p class="kicker">Built on</p><div class="credits">'
              '<p class="cr"><i>Jurors</i>Nebius Token Factory <span>DeepSeek-V4-Pro · Qwen3-235B · gpt-oss-120b</span></p>'
              '<p class="cr"><i>Presiding</i>NVIDIA Nemotron <span>nemotron-3-super-120b-a12b</span></p>'
              '<p class="cr"><i>Proofs</i>Nebius Sandboxes <span>one microVM per claim · MuJoCo for robots</span></p>'
              '<p class="cr"><i>Already known?</i>Tavily + GitHub</p></div>'
              '<p class="url" id="url">polyjury.vercel.app</p><p class="repo">github.com/cine1052rene/polyjury · Apache-2.0'
              ' · narration: AI voice (Supertonic TTS)</p>'
              '<p class="repo" style="color:var(--accent)">try it: Recorded verdict replays a finished case, no setup</p></div>'),
        video("vArm", "arm", S("s0"), "shot wide"),
        video("vTa", "t_a", S("s8"), "shot wide"), video("vTb", "t_b", S("s8") + clip["t_a"], "shot wide"),
        video("vTc", "t_c", S("s8") + clip["t_a"] + clip["t_b"], "shot wide"),
        video("vMa", "m_a", S("s3")), video("vMb", "m_b", S("s3") + clip["m_a"]),
        video("vUp", "m_up", S("s4")),
        video("vF1", "m_fix1", S("s5")), video("vF2", "m_fix2", S("s5") + clip["m_fix1"]),
        video("vCa", "c_a", S("s6")), video("vCb", "c_b", S("s6") + clip["c_a"]),
    ]
    starts = {f"n{i}": round(at[f"s{i}"] + LEAD, 3) for i in range(10)}
    html += [f'<audio id="vo{k}" src="assets/{k}.wav" data-start="{v}" data-duration="{round(n[k], 3)}" '
             f'data-track-index="3"></audio>' for k, v in starts.items()]

    E = '"power3.out"'
    js = [f"const tl = gsap.timeline({{ paused: true }}); const E = {E};",
          "const cnt = (sel, to, at, d, dec) => { const o = {v:0}; tl.to(o, {v:to, duration:d, ease:'power1.out', "
          "onUpdate:()=>{ document.querySelector(sel).textContent = dec ? o.v.toFixed(dec) : Math.round(o.v); }}, at); };"]
    a = lambda k, dt: round(S(k) + dt, 3)  # noqa: E731
    js += [
        f'tl.from("#s0 .side > .kicker, #s0 .side > h2", {{x:40, opacity:0, duration:.6, ease:E, stagger:.15}}, {a("s0", .2)});',
        f'tl.from("#s0 .it", {{x:30, opacity:0, duration:.5, ease:E, stagger:2.2}}, {a("s0", 1.4)});',
        f'tl.from("#h0 p", {{y:20, opacity:0, duration:.5, ease:E, stagger:2.0}}, {a("s0", 7.6)});',
        f'tl.fromTo("#h332", {{y:80, opacity:0}}, {{y:0, opacity:1, duration:.7, ease:E}}, {a("s0", clip["arm"])});',
        f'tl.from("#d1", {{x:-50, opacity:0, duration:.6, ease:E}}, {a("s1", .3)});',
        f'tl.from("#d2", {{x:50, opacity:0, duration:.6, ease:E}}, {a("s1", 3.3)});',
        f'tl.to("#d1", {{opacity:.55, duration:.5}}, {a("s1", 3.6)});',
        f'tl.from(".bdg", {{y:30, opacity:0, duration:.5, ease:E, stagger:1.7}}, {a("s1", 6.0)});',
        f'tl.from("#s2 .kicker, #s2 .title", {{y:30, opacity:0, duration:.6, ease:E, stagger:.12}}, {a("s2", .1)});',
        f'tl.from("#s2 .node", {{y:50, duration:.6, ease:E, stagger:.1}}, {a("s2", .3)});',
        f'tl.set("#s2 .node", {{opacity:.38}}, {a("s2", 0)});',
        f'tl.from(".c", {{scale:.4, opacity:0, duration:.35, ease:"back.out(2)", stagger:.12}}, {a("s2", 1.7)});',
        f'tl.from("#sim", {{y:24, opacity:0, duration:.6, ease:E}}, {a("s2", lens["s2"] - 2.6)});',
    ]
    for i, dt in enumerate([0.9, 3.9, 6.1, 8.2], 1):
        js.append(f'tl.to("#f{i}", {{opacity:1, duration:.35}}, {a("s2", dt)}).to("#f{i} .lit", {{opacity:1, duration:.35}}, {a("s2", dt)});')
        if i < 4:
            js.append(f'tl.to("#k{i}", {{scaleX:1, duration:.9, ease:"power2.inOut"}}, {a("s2", dt + .9)});')
    for k, sub in (("s3", ("b3a", "b3b", clip["m_a"])), ("s5", ("b5a", "b5b", clip["m_fix1"])),
                   ("s6", ("b6a", "b6b", clip["c_a"]))):
        x, y, cut = sub
        js += [f'tl.from("#{k} .frame", {{opacity:0, duration:.4}}, {a(k, 0)});',
               f'tl.from("#{k} .side > .kicker, #{k} .side > h2, #{k} .side > .src", {{x:40, opacity:0, duration:.55, ease:E, stagger:.12}}, {a(k, .15)});',
               f'tl.from("#{k} .it", {{x:30, opacity:0, duration:.45, ease:E, stagger:1.3}}, {a(k, .9)});',
               f'tl.set("#{y}", {{opacity:0}}, {a(k, 0)}).set("#{x}", {{opacity:0}}, {a(k, cut)}).set("#{y}", {{opacity:1}}, {a(k, cut)});']
    js += [
        f'tl.from("#v3", {{y:30, opacity:0, duration:.6, ease:E}}, {a("s3", lens["s3"] - 5.0)});',
        f'tl.from("#v5", {{y:30, opacity:0, duration:.6, ease:E}}, {a("s5", 5.0)});',
        f'tl.from("#v6", {{scale:1.3, opacity:0, duration:.5, ease:"back.out(2)"}}, {a("s6", clip["c_a"] + 1.0)});',
        f'tl.from("#s4 .frame", {{opacity:0, duration:.4}}, {a("s4", 0)});',
        f'tl.from("#s4 .side > .kicker, #s4 .side > h2", {{x:40, opacity:0, duration:.55, ease:E, stagger:.12}}, {a("s4", .15)});',
        f'tl.from("#s4 .it", {{x:30, opacity:0, duration:.45, ease:E, stagger:1.6}}, {a("s4", 1.0)});',
        f'tl.set("#p332", {{opacity:0}}, {a("s4", 0)});',
        f'tl.set("#b4", {{opacity:0}}, {round(up_card, 3)});',
        f'tl.fromTo("#p332", {{y:100, opacity:0}}, {{y:0, opacity:1, duration:.7, ease:E}}, {round(up_card, 3)});',
        f'tl.from("#v4 p", {{y:20, opacity:0, duration:.5, ease:E}}, {round(up_card + .4, 3)});',
        f'tl.from("#s7 .kicker, #s7 .title", {{y:30, opacity:0, duration:.6, ease:E, stagger:.12}}, {a("s7", .1)});',
        f'tl.from("#s7 .stat, .a7", {{y:30, opacity:0, duration:.5, ease:E, stagger:.25}}, {a("s7", .6)});',
        f'tl.fromTo("#nah", {{scale:1.8, opacity:0, rotation:-6}}, {{scale:1, opacity:1, rotation:-3, duration:.45, ease:"back.out(2.2)"}}, {a("s7", 6.2)});',
        f'tl.from("#refs p", {{y:20, opacity:0, duration:.5, ease:E, stagger:.5}}, {a("s7", 7.4)});',
        f'tl.from("#s8 .side > .kicker, #s8 .side > h2", {{x:40, opacity:0, duration:.55, ease:E, stagger:.12}}, {a("s8", .15)});',
        f'tl.from("#s8 .it", {{x:30, opacity:0, duration:.45, ease:E, stagger:2.6}}, {a("s8", 1.0)});',
        f'tl.set("#b8b", {{opacity:0}}, {a("s8", 0)}).set("#b8a", {{opacity:0}}, {a("s8", clip["t_a"])}).set("#b8b", {{opacity:1}}, {a("s8", clip["t_a"])});',
        f'tl.from("#s9 .kicker, .cr", {{x:-30, opacity:0, duration:.55, ease:E, stagger:1.4}}, {a("s9", .2)});',
        f'tl.from("#url, #s9 .repo", {{y:30, opacity:0, duration:.7, ease:E, stagger:.3}}, {a("s9", 6.4)});',
        f'tl.to("#root .pad, #root .side", {{opacity:0, duration:.8}}, {round(total - .9, 3)});',
    ]
    js += [f'cnt("#q1", 8, {a("s7", .9)}, 1.0); cnt("#q2", 11, {a("s7", 2.0)}, 1.0); cnt("#q3", 2, {a("s7", 3.6)}, .6);',
           'window.__timelines["main"] = tl;']
    page = ("<!doctype html><html lang=\"en\"><head><meta charset=\"UTF-8\" />"
            "<meta name=\"viewport\" content=\"width=1920, height=1080\" /><title>Polyjury demo v6</title>"
            "<script src=\"https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js\"></script>"
            "<link href=\"https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&"
            "family=JetBrains+Mono:wght@500;700&display=swap\" rel=\"stylesheet\" />"
            f"<style>{CSS}</style></head><body>"
            f'<div id="root" data-composition-id="main" data-start="0" data-width="1920" data-height="1080" '
            f'data-duration="{total}"><div class="bg"></div><div class="glow"></div>'
            + "\n".join(html) + "</div><script>\n" + "\n".join(js) + "\n</script></body></html>")
    (HF / "index.html").write_text(page, encoding="utf-8")
    (PRESS / "build-v6" / "timeline.json").write_text(json.dumps({"starts": starts, "scenes": at, "total": total}, indent=1))
    print("total", total, "s")
    for k in at:
        print(f"  {k} {at[k]:6.2f} +{lens[k]:5.2f}")


if __name__ == "__main__":
    build()
