"""Cut the live recording into the demo video.

Segments are placed from the event log written during the recording, so each
caption sits on the stage it describes. Waiting for models is sped up, and the
speed is printed on screen: the viewer is never told a run took less than it did.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

from build_demo_video import ACC, INK, MUT, H, W, card_png, font, run

PRESS = Path(__file__).resolve().parents[1] / "private" / "press"
WORK = PRESS / "build-live"
FPS = 25


def events() -> dict[str, float]:
    log = json.loads((PRESS / "live-events.json").read_text(encoding="utf-8"))
    t: dict[str, float] = {}
    for e in log:
        key = e["event"] if e["event"] != "step" else f"step{e['n']}"
        if key == "api:prove":
            t.setdefault("first_proof", e["t"])
            t["proofs"] = t.get("proofs", 0) + 1
            if e.get("verdict") == "REPRODUCED":
                t["last_confirmed"] = e["t"]
            continue
        t.setdefault(key, e["t"])
    return t


def caption_png(path: Path, title: str, sub: str, badge: str = "") -> None:
    img = Image.new("RGBA", (W, 128), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 128], fill=(8, 10, 15, 222))
    d.line([(0, 0), (W, 0)], fill=(*ACC, 190), width=2)
    d.text((56, 24), title, font=font(34, True), fill=(*INK, 255))
    d.text((56, 74), sub, font=font(22), fill=(*MUT, 255))
    if badge:
        f = font(22, True)
        w = d.textlength(badge, font=f)
        x = W - 56 - w - 28
        d.rounded_rectangle([x, 40, W - 56, 86], radius=23, outline=(*ACC, 255), width=2)
        d.text((x + 14, 49), badge, font=f, fill=(*ACC, 255))
    img.save(path)


def plan(t: dict[str, float]) -> list[tuple[float, float, float, str, str]]:
    """(start, end, speed, title, subtitle) in raw-recording seconds."""
    def fit(start: float, end: float, seconds: float) -> float:
        return max(1.0, round((end - start) / seconds))

    s = [
        (0.3, t["submit"] + 1.0, 1.0, "Paste a public repository",
         "this is the live site — nothing below is replayed"),
        (t["submit"] + 1.0, t["step3"], None, "Three jurors read it, separately",
         "DeepSeek-V4-Pro · Qwen3.5-397B · gpt-oss-120b on Nebius Token Factory"),
        (t["step3"], t["step4"], None, "NVIDIA Nemotron presides",
         "merges what the jurors said, drops what cannot be checked by running code"),
        (t["step4"], t["last_confirmed"] + 1.5, None, "Every claim has to prove itself",
         "Nemotron writes a script per claim — each runs in its own Nebius Sandbox microVM"),
        (t["last_confirmed"] + 1.5, t["verdict"], None, "Some claims fall apart when run",
         "false alarms are reported as false alarms, not as findings"),
        (t["verdict"], t["open-proof"], 1.0, "Only what reproduced is reported",
         "the count is of runs, not of opinions"),
        (t["open-proof"], t["final"], 1.0, "The evidence is the run's own output",
         "and the proof Nemotron wrote sits right under it"),
        (t["final"], t["end"], 1.0, "A prompt to paste back",
         "to the AI that wrote the code — confirmed defects only"),
    ]
    target = {1: 7, 2: 6, 3: 9, 4: 7}
    return [(a, b, sp if sp else fit(a, b, target[i]), ti, su) for i, (a, b, sp, ti, su) in enumerate(s)]


def main() -> None:
    raw = PRESS / "live-raw.webm"
    WORK.mkdir(parents=True, exist_ok=True)
    segments = plan(events())

    card_png(WORK / "title.png", [
        ("Polyjury", 92, INK, True),
        ("One AI wrote your code.", 40, MUT, False),
        ("Don't let one AI judge it.", 40, MUT, False),
        ("no bug report without a repro", 30, ACC, True),
    ])
    card_png(WORK / "outro.png", [
        ("Every claim is proved by running it,", 36, INK, False),
        ("in a Nebius Token Factory Sandbox.", 36, INK, False),
        ("", 18, INK, False),
        ("polyjury.vercel.app", 34, ACC, True),
        ("github.com/cine1052rene/polyjury", 26, MUT, False),
    ])

    parts = []
    title_mp4 = WORK / "title.mp4"
    run(["ffmpeg", "-y", "-loop", "1", "-t", "4", "-i", str(WORK / "title.png"), "-c:v", "libx264",
         "-pix_fmt", "yuv420p", "-r", str(FPS), "-vf", f"scale={W}:{H}", str(title_mp4)])
    parts.append(title_mp4)

    for i, (start, end, speed, title, sub) in enumerate(segments):
        cap = WORK / f"cap{i}.png"
        caption_png(cap, title, sub, f"{speed:g}× speed" if speed > 1 else "")
        out = WORK / f"seg{i}.mp4"
        run(["ffmpeg", "-y", "-ss", f"{start:.2f}", "-to", f"{end:.2f}", "-i", str(raw), "-i", str(cap),
             "-filter_complex", f"[0:v]setpts=(PTS-STARTPTS)/{speed},fps={FPS}[v];[v][1:v]overlay=0:H-h-24",
             "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", str(out)])
        parts.append(out)
        print(f"seg{i}: {start:6.1f}-{end:6.1f}s  x{speed:g} -> {(end - start) / speed:4.1f}s  {title}")

    outro_mp4 = WORK / "outro.mp4"
    run(["ffmpeg", "-y", "-loop", "1", "-t", "5", "-i", str(WORK / "outro.png"), "-c:v", "libx264",
         "-pix_fmt", "yuv420p", "-r", str(FPS), "-vf", f"scale={W}:{H}", str(outro_mp4)])
    parts.append(outro_mp4)

    listing = WORK / "concat.txt"
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    final = PRESS / "polyjury-demo-live.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(final)])
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(final)], capture_output=True, text=True).stdout.strip()
    print(f"{final} - {float(dur):.1f}s, {final.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
