"""Assemble the submission video (under three minutes) from three real recordings:

  private/press/arm-collision.mp4   MuJoCo render of SO-ARM100's elbow driving the gripper into the shoulder
  private/press/robot-raw.webm      the live site judging that repository folder  (+ robot-events.json)
  private/press/code-raw.webm       the live site judging fastapi-cli             (+ code-events.json)

Waiting for models is sped up and the speed is printed on screen. Nothing is replayed or mocked.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from build_demo_video import ACC, INK, MUT, H, W, card_png, run
from build_live_video import caption_png

PRESS = Path(__file__).resolve().parents[1] / "private" / "press"
WORK = PRESS / "build-final"
FPS = 25
JURORS = "DeepSeek-V4-Pro · Qwen3-235B · gpt-oss-120b on Nebius Token Factory"


def events(name: str) -> dict[str, float]:
    t: dict[str, float] = {}
    for e in json.loads((PRESS / f"{name}-events.json").read_text(encoding="utf-8")):
        key = e["event"] if e["event"] != "step" else f"step{e['n']}"
        if key == "api:prove":
            t.setdefault("first_proof", e["t"])
            if e.get("verdict") == "REPRODUCED":
                t["last_confirmed"] = e["t"]
            continue
        t.setdefault(key, e["t"])
    return t


def fit(start: float, end: float, seconds: float) -> float:
    return max(1.0, round((end - start) / seconds))


def robot_plan(t: dict[str, float]) -> list[tuple[float, float, float, str, str]]:
    end_proofs = t.get("last_confirmed", t["verdict"] - 1.5) + 1.5
    return [
        (0.3, t["submit"] + 1.0, 1.0, "Paste the robot's own repository folder",
         "the live site — a URDF is code too"),
        (t["submit"] + 1.0, t["step3"], fit(t["submit"] + 1.0, t["step3"], 6), "Three jurors read the files, separately",
         JURORS),
        (t["step3"], t["step4"], fit(t["step3"], t["step4"], 5), "NVIDIA Nemotron presides",
         "merges the reviews — and adds one claim no juror can make by reading: a simulation"),
        (t["step4"], end_proofs, fit(t["step4"], end_proofs, 9), "Every claim has to prove itself",
         "MuJoCo and the meshes go into a Nebius Sandbox microVM; each joint is swept alone"),
        (end_proofs, t["verdict"], fit(end_proofs, t["verdict"], 4), "The jurors' own claims are tested too",
         "what does not reproduce is reported as a false alarm"),
        (t["verdict"], t["open-proof"], 1.0, "Reproduced: the collision, from the file's own limits",
         "no juror found it by reading — the simulation did"),
        (t["open-proof"], t["final"], 1.0, "The evidence is the run's output",
         "onset angle, exact mesh overlap in mm³ — measured, not guessed"),
    ]


def code_plan(t: dict[str, float]) -> list[tuple[float, float, float, str, str]]:
    end_proofs = t.get("last_confirmed", t["verdict"] - 1.5) + 1.5
    s = [
        (0.3, t["submit"] + 1.0, 1.0, "It started with code — paste any public repository",
         "fastapi-cli, live"),
        (t["submit"] + 1.0, t["step4"], fit(t["submit"] + 1.0, t["step4"], 8), "Jurors review, Nemotron merges and writes a proof per claim",
         "a Python script that tries to make the defect happen"),
        (t["step4"], end_proofs, fit(t["step4"], end_proofs, 8), "Each proof runs in its own Sandbox",
         "the repository's declared dependencies are installed first"),
        (end_proofs, t["verdict"], fit(end_proofs, t["verdict"], 4), "Then Nemotron audits every run",
         "a verdict its own output does not support is thrown out"),
        (t["verdict"], t["open-proof"], 1.0, "Only what reproduced is reported",
         "the count is of runs, not of opinions"),
        (t["open-proof"], t.get("open-audit", t["final"]), 1.0, "Request, response, the file it wrote",
         "the proof Nemotron wrote sits right under the output"),
    ]
    if "open-audit" in t:
        s.append((t["open-audit"], t["final"], 1.0, "And one the audit rejected",
                  "the script printed REPRODUCED and nothing that showed it happen — thrown out, not counted"))
    s.append((t["final"], t["end"], 1.0, "A prompt to paste back to the AI that wrote the code",
              "confirmed defects only"))
    return s


def cut(src: Path, out: Path, start: float, end: float, speed: float, title: str, sub: str) -> None:
    cap = out.with_suffix(".png")
    caption_png(cap, title, sub, f"{speed:g}× speed" if speed > 1 else "")
    run(["ffmpeg", "-y", "-ss", f"{start:.2f}", "-to", f"{end:.2f}", "-i", str(src), "-i", str(cap),
         "-filter_complex", f"[0:v]setpts=(PTS-STARTPTS)/{speed},scale={W}:{H},fps={FPS}[v];[v][1:v]overlay=0:H-h-24",
         "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", str(out)])
    print(f"{out.name}: {start:6.1f}-{end:6.1f}s x{speed:g} -> {(end - start) / speed:4.1f}s  {title}")


def still(png: Path, out: Path, seconds: float) -> None:
    run(["ffmpeg", "-y", "-loop", "1", "-t", str(seconds), "-i", str(png), "-c:v", "libx264",
         "-pix_fmt", "yuv420p", "-r", str(FPS), "-vf", f"scale={W}:{H}", str(out)])


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []

    card_png(WORK / "title.png", [
        ("Polyjury", 92, INK, True),
        ("One AI wrote your code.", 40, MUT, False),
        ("Don't let one AI judge it.", 40, MUT, False),
        ("no bug report without a repro — for code, and for robots", 30, ACC, True),
    ])
    still(WORK / "title.png", WORK / "title.mp4", 4)
    parts.append(WORK / "title.mp4")

    arm = PRESS / "arm-collision.mp4"
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                "default=nw=1:nk=1", str(arm)], capture_output=True, text=True).stdout)
    cut(arm, WORK / "arm.mp4", 0, dur, 1.0, "SO-ARM100, an open-source robot arm — inside its own joint limits",
        "rendered from the repository's URDF with MuJoCo: the gripper enters the shoulder at 86.5°, the file allows 96.8°")
    parts.append(WORK / "arm.mp4")

    for name, plan in (("robot", robot_plan), ("code", code_plan)):
        for i, (a, b, sp, ti, su) in enumerate(plan(events(name))):
            out = WORK / f"{name}{i}.mp4"
            cut(PRESS / f"{name}-raw.webm", out, a, b, sp, ti, su)
            parts.append(out)

    card_png(WORK / "outro.png", [
        ("Every claim is proved by running it,", 36, INK, False),
        ("in a Nebius Token Factory Sandbox.", 36, INK, False),
        ("", 18, INK, False),
        ("polyjury.vercel.app", 34, ACC, True),
        ("github.com/cine1052rene/polyjury", 26, MUT, False),
    ])
    still(WORK / "outro.png", WORK / "outro.mp4", 5)
    parts.append(WORK / "outro.mp4")

    listing = WORK / "concat.txt"
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    final = PRESS / "polyjury-demo-v3.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(final)])
    total = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                            "default=nw=1:nk=1", str(final)], capture_output=True, text=True).stdout.strip()
    print(f"{final} - {float(total):.1f}s, {final.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
