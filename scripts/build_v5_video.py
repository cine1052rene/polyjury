"""Assemble demo video v5 (under three minutes), narrated, with captions in a side panel.

Sources, all real:
  private/press/arm-collision.mp4     MuJoCo render of the SO-101 elbow (render_arm.py)
  private/press/menagerie-raw.webm    live site judging DeepMind's Menagerie SO-101, recorded 11 Oct (+ -events.json)
  private/press/code-raw.webm         live site judging fastapi-cli, recorded 27 Sep (+ -events.json)
  private/press/build-v5/pr332.png, issue325.png   GitHub pages, captured 11 Oct
  private/press/narration-v5/n*.wav   voice-over (scripts/narrate_v5.py)

The recordings were made with the Sources drawer open on the right; that column is covered by the
caption panel, so the bottom of the frame stays free for YouTube's CC subtitles. Waits for the
models are sped up and the speed is printed in the panel. Writes polyjury-demo-v5.mp4 and
build-v5/timeline.json (where each narration clip starts, for make_captions_v5.py).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

from build_demo_video import ACC, BG, INK, MUT, H, W, card_png, font, run

PRESS = Path(__file__).resolve().parents[1] / "private" / "press"
WORK, VOICE = PRESS / "build-v5", PRESS / "narration-v5"
FPS = 25
PANEL_X = 918           # the Sources drawer starts here in the recordings
LEAD, TAIL = 0.25, 0.6  # silence before / after each narration clip
JURORS = "DeepSeek-V4-Pro, Qwen3-235B and gpt-oss-120b on Nebius Token Factory"


def duration(p: Path) -> float:
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                 "default=nw=1:nk=1", str(p)], capture_output=True, text=True).stdout)


def events(name: str) -> dict[str, float]:
    t: dict[str, float] = {}
    for e in json.loads((PRESS / f"{name}-events.json").read_text(encoding="utf-8")):
        key = e["event"] if e["event"] != "step" else f"step{e['n']}"
        if not key.startswith("api:"):
            t.setdefault(key, e["t"])
    return t


def wrap(d: ImageDraw.ImageDraw, text: str, f, width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if d.textlength(trial, font=f) <= width:
            line = trial
        else:
            lines.append(line)
            line = word
    return lines + ([line] if line else [])


def panel_png(path: Path, title: str, sub: str, badge: str = "") -> None:
    """The right-hand column: an opaque panel with the caption, over the recording's Sources drawer."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([PANEL_X, 0, W, H], fill=(*BG, 255))
    d.line([(PANEL_X, 0), (PANEL_X, H)], fill=(*ACC, 150), width=2)
    x, width, y = PANEL_X + 30, W - PANEL_X - 56, 64
    tf, sf = font(30, True), font(21)
    for line in wrap(d, title, tf, width):
        d.text((x, y), line, font=tf, fill=(*INK, 255))
        y += 40
    y += 18
    for line in wrap(d, sub, sf, width):
        d.text((x, y), line, font=sf, fill=(*MUT, 255))
        y += 30
    if badge:
        bf = font(21, True)
        w = d.textlength(badge, font=bf)
        d.rounded_rectangle([x, H - 110, x + w + 28, H - 66], radius=22, outline=(*ACC, 255), width=2)
        d.text((x + 14, H - 102), badge, font=bf, fill=(*ACC, 255))
    img.save(path)


def footage(src: Path, out: Path, start: float, end: float, speed: float, title: str, sub: str,
            fit_left: bool = False) -> None:
    """A stretch of a recording, sped up if waiting, with the panel on the right. fit_left scales a
    full-frame source (the MuJoCo render) into the area left of the panel instead of covering it."""
    cap = out.with_suffix(".png")
    panel_png(cap, title, sub, f"{speed:g}× speed" if speed > 1 else "")
    if fit_left:
        h = round(PANEL_X * H / W / 2) * 2
        video = (f"[0:v]setpts=(PTS-STARTPTS)/{speed},scale={PANEL_X}:{h},"
                 f"pad={W}:{H}:0:{(H - h) // 2}:color=0x{BG[0]:02x}{BG[1]:02x}{BG[2]:02x},fps={FPS}[v]")
    else:
        video = f"[0:v]setpts=(PTS-STARTPTS)/{speed},scale={W}:{H},fps={FPS}[v]"
    run(["ffmpeg", "-y", "-ss", f"{start:.2f}", "-to", f"{end:.2f}", "-i", str(src), "-i", str(cap),
         "-filter_complex", f"{video};[v][1:v]overlay=0:0", "-an", "-c:v", "libx264", "-preset", "medium",
         "-crf", "20", "-pix_fmt", "yuv420p", str(out)])
    print(f"  {out.name}: {start:6.1f}-{end:6.1f}s x{speed:g} -> {(end - start) / speed:4.1f}s  {title}")


def page(shot: Path, out: Path, seconds: float, title: str, sub: str) -> None:
    """A captured web page, fitted left of the panel."""
    frame = Image.new("RGB", (W, H), BG)
    img = Image.open(shot).convert("RGB")
    scale = min((PANEL_X - 40) / img.width, (H - 40) / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)))
    frame.paste(img, ((PANEL_X - img.width) // 2, (H - img.height) // 2))
    cap = out.with_suffix(".cap.png")
    panel_png(cap, title, sub)
    frame.paste(Image.open(cap), (0, 0), Image.open(cap))
    frame.save(out.with_suffix(".png"))
    still(out.with_suffix(".png"), out, seconds)


def still(png: Path, out: Path, seconds: float) -> None:
    run(["ffmpeg", "-y", "-loop", "1", "-t", f"{seconds:.2f}", "-i", str(png), "-c:v", "libx264",
         "-pix_fmt", "yuv420p", "-r", str(FPS), "-vf", f"scale={W}:{H}", str(out)])


def hold(clip: Path, seconds: float) -> Path:
    out = clip.with_name(clip.stem + "-held.mp4")
    run(["ffmpeg", "-y", "-i", str(clip), "-vf", f"tpad=stop_mode=clone:stop_duration={seconds:.2f}",
         "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", str(out)])
    return out


def groups() -> list[tuple[str, list]]:
    """(narration clip, [builder calls]) in order. Each builder is (function, kwargs)."""
    m, c = events("menagerie"), events("code")
    mraw, craw = PRESS / "menagerie-raw.webm", PRESS / "code-raw.webm"
    card_png(WORK / "title.png", [
        ("Polyjury", 92, INK, True),
        ("Find it. Prove it. Fix it.", 40, INK, False),
        ("Prove the fix. Check nobody reported it first.", 40, MUT, False),
        ("for code — and for robots", 30, ACC, True),
    ])
    card_png(WORK / "field.png", [
        ("In the field", 56, INK, True),
        ("8 public repositories  ·  11 claims reproduced", 36, INK, False),
        ("checked by hand: 2 real defects, 9 not defects", 36, MUT, False),
        ("(intended behaviour, or differences too small to matter)", 26, MUT, False),
        ("both real ones: DeepMind Menagerie SO-101 → issue #325", 30, ACC, True),
    ])
    card_png(WORK / "outro.png", [
        ("Jurors on Nebius Token Factory", 38, INK, False),
        ("NVIDIA Nemotron as the judge", 38, INK, False),
        ("Sandboxes run every proof · Tavily checks what is known", 30, MUT, False),
        ("polyjury.vercel.app", 36, ACC, True),
        ("github.com/cine1052rene/polyjury · Apache-2.0", 26, MUT, False),
    ])
    arm = PRESS / "arm-collision.mp4"
    return [
        ("n0", [(still, dict(png=WORK / "title.png", out=WORK / "g0.mp4", seconds=4))]),
        ("n1", [(footage, dict(src=arm, out=WORK / "g1.mp4", start=0, end=duration(arm), speed=1, fit_left=True,
                               title="SO-101, inside its own joint limits",
                               sub="MuJoCo render from the SO-ARM100 repository's URDF: the gripper enters the "
                                   "shoulder at 86.5°, the file allows 96.8°"))]),
        ("n2", [(footage, dict(src=mraw, out=WORK / "g2a.mp4", start=m["loaded"], end=m["step2"], speed=2,
                               title="DeepMind's MuJoCo Menagerie model of the same arm",
                               sub="pasted into the live site, recorded 11 Oct — nothing is replayed")),
                (footage, dict(src=mraw, out=WORK / "g2b.mp4", start=m["step2"], end=m["step4"], speed=2,
                               title="Three jurors read it, separately",
                               sub=f"{JURORS}. NVIDIA Nemotron merges them, and adds a simulation claim"))]),
        ("n3", [(footage, dict(src=mraw, out=WORK / "g3.mp4", start=m["step4"], end=m["step5"], speed=8,
                               title="Every claim proves itself in a Nebius Sandbox microVM",
                               sub="MuJoCo and the meshes go in; each joint is swept alone. "
                                   "Reproduced: the elbow. Five juror claims: false alarms"))]),
        ("n4", [(footage, dict(src=mraw, out=WORK / "g4a.mp4", start=m["open-upstream"], end=m["open-fix"], speed=1,
                               title="Already reported?",
                               sub="the repository's issues and pull requests, plus Tavily web search — "
                                   "Nemotron decides whether a hit is the same defect")),
                (page, dict(shot=WORK / "issue325.png", out=WORK / "g4b.mp4", seconds=5,
                            title="Issue #325",
                            sub="filed 28 Sep from an earlier Polyjury run, with the measurements")),
                (page, dict(shot=WORK / "pr332.png", out=WORK / "g4c.mp4", seconds=6,
                            title="Pull request #332",
                            sub="opened by another contributor: \"Fixes #325\". Open, not yet merged (11 Oct)"))]),
        ("n5", [(footage, dict(src=mraw, out=WORK / "g5a.mp4", start=m["step6"], end=m["fix-done"], speed=5,
                               title="Fix it, then prove the fix",
                               sub="the same sealed proof runs on the untouched file, then on the patched one")),
                (footage, dict(src=mraw, out=WORK / "g5b.mp4", start=m["open-fix"], end=m["final"], speed=1,
                               title="Fixed — and the proof says so",
                               sub="elbow_flex 1.69 → 1.5594 rad, re-run: NOT_REPRODUCED. Cost: 7.5° of travel. "
                                   "(Contacts under 3 mm are ignored; PR #332 chose a stricter 1.45 rad)"))]),
        ("n6", [(footage, dict(src=craw, out=WORK / "g6a.mp4", start=c["submit"], end=c["step4"], speed=8,
                               title="Ordinary code, the same way",
                               sub="fastapi-cli on the live site, recorded 27 Sep")),
                (footage, dict(src=craw, out=WORK / "g6b.mp4", start=c["step4"], end=c["verdict"], speed=12,
                               title="Each proof runs in its own Sandbox",
                               sub="with the repository's declared dependencies; then Nemotron audits every run")),
                (footage, dict(src=craw, out=WORK / "g6c.mp4", start=c["open-audit"], end=c["final"], speed=1,
                               title="One the audit rejected",
                               sub="the script printed REPRODUCED and nothing that showed it happen — thrown out"))]),
        ("n7", [(still, dict(png=WORK / "field.png", out=WORK / "g7.mp4", seconds=4))]),
        ("n8", [(still, dict(png=WORK / "outro.png", out=WORK / "g8.mp4", seconds=4))]),
    ]


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    parts, starts, t = [], {}, 0.0
    for clip, builders in groups():
        outs = []
        for fn, kw in builders:
            fn(**kw)
            outs.append(kw["out"])
        voice = VOICE / f"{clip}.wav"
        video = sum(duration(o) for o in outs)
        extra = max(0.0, LEAD + duration(voice) + TAIL - video)
        if extra > 0.05:
            outs[-1] = hold(outs[-1], extra)
        starts[clip] = round(t + LEAD, 3)
        parts += outs
        t += video + extra
        print(f"{clip}: video {video:5.1f}s voice {duration(voice):5.1f}s hold +{extra:.1f}s  -> at {t:6.1f}s")

    listing = WORK / "concat.txt"
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    silent = WORK / "v5-silent.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(silent)])

    inputs, chains = ["-i", str(silent)], []
    for i, (clip, s) in enumerate(starts.items()):
        inputs += ["-i", str(VOICE / f"{clip}.wav")]
        ms = int(s * 1000)
        chains.append(f"[{i + 1}:a]aresample=48000,adelay={ms}|{ms}[a{i}]")
    mix = ";".join(chains) + ";" + "".join(f"[a{i}]" for i in range(len(starts))) + \
        f"amix=inputs={len(starts)}:normalize=0,loudnorm=I=-16:TP=-1.5[a]"
    final = PRESS / "polyjury-demo-v5.mp4"
    run(["ffmpeg", "-y", *inputs, "-filter_complex", mix, "-map", "0:v", "-map", "[a]", "-c:v", "copy",
         "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-shortest", str(final)])
    total = duration(final)
    (WORK / "timeline.json").write_text(json.dumps({"starts": starts, "total": total}, indent=1), encoding="utf-8")
    assert total < 180, total
    print(f"{final} - {total:.1f}s, {final.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
