"""Turn the raw screen recording into the submitted demo: title, captions, outro.

Captions are rendered as transparent PNG strips and overlaid, which avoids fighting
ffmpeg's drawtext escaping on Windows and keeps the typography the same as the site.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PRESS = Path(__file__).resolve().parents[1] / "private" / "press"
WORK = PRESS / "build"
W, H = 1280, 720
BG, INK, MUT, ACC = (10, 12, 17), (233, 237, 245), (139, 149, 171), (118, 227, 161)

CAPTIONS = [
    (0.0, 6.0, "A workbench, not a chat box", "three jurors on Nebius Token Factory, one presiding judge"),
    (6.0, 13.0, "A finished case, replayed", "tiangolo/fastapi-cli — a real public repository"),
    (13.0, 21.0, "The jury reads it separately", "each model sees the same code and none of the other answers"),
    (21.0, 27.0, "They do not agree", "most findings are raised by one juror only"),
    (27.0, 34.0, "Nemotron presides", "merges duplicates, drops what cannot be checked by running code"),
    (34.0, 41.0, "Every claim has to prove itself", "Nemotron writes a script; the verdict is what the run printed"),
    (41.0, 44.0, "6 reproduced. 2 false alarms.", "no bug report without a repro"),
]


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for name in (("segoeuib.ttf" if bold else "segoeui.ttf"), ("arialbd.ttf" if bold else "arial.ttf")):
        try:
            return ImageFont.truetype("C:/Windows/Fonts/" + name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def caption_png(path: Path, title: str, sub: str) -> None:
    img = Image.new("RGBA", (W, 128), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 128], fill=(8, 10, 15, 214))
    d.line([(0, 0), (W, 0)], fill=(*ACC, 190), width=2)
    d.text((56, 26), title, font=font(34, True), fill=(*INK, 255))
    d.text((56, 74), sub, font=font(22), fill=(*MUT, 255))
    img.save(path)


def card_png(path: Path, lines: list[tuple[str, int, tuple, bool]]) -> None:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    y = 210
    for text, size, colour, bold in lines:
        d.text((96, y), text, font=font(size, bold), fill=colour)
        y += int(size * 1.7)
    img.save(path)


def run(args: list[str]) -> None:
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode:
        print(proc.stderr[-1500:])
        raise SystemExit(f"ffmpeg failed: {' '.join(args[:3])}")


def main() -> None:
    raw = PRESS / "demo-raw.webm"
    if not raw.exists():
        raise SystemExit("record the screen first: scripts/record_demo.py")
    WORK.mkdir(parents=True, exist_ok=True)

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
    for i, (_, _, title, sub) in enumerate(CAPTIONS):
        caption_png(WORK / f"cap{i}.png", title, sub)

    # captions over the footage
    inputs: list[str] = ["-i", str(raw)]
    for i in range(len(CAPTIONS)):
        inputs += ["-i", str(WORK / f"cap{i}.png")]
    chain, last = [], "0:v"
    for i, (start, end, _, _) in enumerate(CAPTIONS):
        tag = f"v{i}"
        chain.append(f"[{last}][{i + 1}:v]overlay=0:H-h-28:enable='between(t,{start},{end})'[{tag}]")
        last = tag
    body = WORK / "body.mp4"
    run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(chain), "-map", f"[{last}]",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
         "-r", "25", str(body)])

    # title and outro as still segments
    title_mp4, outro_mp4 = WORK / "title.mp4", WORK / "outro.mp4"
    for png, out, seconds in ((WORK / "title.png", title_mp4, 4), (WORK / "outro.png", outro_mp4, 5)):
        run(["ffmpeg", "-y", "-loop", "1", "-t", str(seconds), "-i", str(png),
             "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
             "-r", "25", "-vf", f"scale={W}:{H}", str(out)])

    listing = WORK / "concat.txt"
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in (title_mp4, body, outro_mp4)), encoding="utf-8")
    final = PRESS / "polyjury-demo.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(final)])

    size = final.stat().st_size // 1024
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(final)], capture_output=True, text=True).stdout.strip()
    print(f"{final} — {dur}s, {size} KB")


if __name__ == "__main__":
    main()
