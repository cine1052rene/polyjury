"""Lay the English narration over the assembled demo (build_final_video.py must have run).

Each narration clip belongs to a run of video parts; where the voice is longer than the picture,
the last frame of that run is held (no footage is sped up or cut). Clips: private/press/narration/n*.wav
(Supertonic TTS, voice F1). Output: private/press/polyjury-demo-v4.mp4, which must stay under 3 minutes.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from build_demo_video import run

PRESS = Path(__file__).resolve().parents[1] / "private" / "press"
WORK, VOICE = PRESS / "build-final", PRESS / "narration"
LEAD, TAIL = 0.2, 0.5   # silence before each clip starts / after it ends
GROUPS = [["title"], ["arm"], ["robot0", "robot1", "robot2"], ["robot3", "robot4"], ["robot5", "robot6"],
          ["code0", "code1"], ["code2", "code3", "code4"], ["code5", "code6"], ["code7"], ["outro"]]


def duration(p: Path) -> float:
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                 "default=nw=1:nk=1", str(p)], capture_output=True, text=True).stdout)


def main() -> None:
    parts, starts, t = [], [], 0.0
    for i, group in enumerate(GROUPS):
        clip = VOICE / f"n{i}.wav"
        video = sum(duration(WORK / f"{g}.mp4") for g in group)
        hold = max(0.0, LEAD + duration(clip) + TAIL - video)
        starts.append(t + LEAD)
        for g in group[:-1]:
            parts.append(WORK / f"{g}.mp4")
        last = WORK / f"{group[-1]}.mp4"
        if hold > 0.05:
            held = WORK / f"{group[-1]}-held.mp4"
            run(["ffmpeg", "-y", "-i", str(last), "-vf", f"tpad=stop_mode=clone:stop_duration={hold:.2f}",
                 "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", str(held)])
            last = held
        parts.append(last)
        print(f"n{i}: {'+'.join(group):24s} video {video:5.1f}s  voice {duration(clip):5.1f}s  hold +{hold:.1f}s")
        t += video + hold

    listing = WORK / "concat-v4.txt"
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    silent = WORK / "v4-silent.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(silent)])

    inputs, chains = ["-i", str(silent)], []
    for i, s in enumerate(starts):
        inputs += ["-i", str(VOICE / f"n{i}.wav")]
        ms = int(s * 1000)
        chains.append(f"[{i + 1}:a]aresample=48000,adelay={ms}|{ms}[a{i}]")
    mix = ";".join(chains) + ";" + "".join(f"[a{i}]" for i in range(len(starts))) + \
        f"amix=inputs={len(starts)}:normalize=0,loudnorm=I=-16:TP=-1.5[a]"
    final = PRESS / "polyjury-demo-v4.mp4"
    run(["ffmpeg", "-y", *inputs, "-filter_complex", mix, "-map", "0:v", "-map", "[a]", "-c:v", "copy",
         "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-shortest", str(final)])
    total = duration(final)
    assert total < 180, total
    print(f"{final} - {total:.1f}s, {final.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
