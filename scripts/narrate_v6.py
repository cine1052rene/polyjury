"""Voice the v6 narration (Supertonic TTS, voice F1) and check every clip by transcribing it.

private/press/narration-v6/script.json holds, per clip, what the voice says ("say", with product
names spelled the way they should sound) and what the captions show ("text", spelled correctly).
Usage: python scripts/narrate_v5.py [n0 n2 ...]   (no arguments = every clip)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from faster_whisper import WhisperModel
from supertonic import TTS

DIR = Path(__file__).resolve().parents[1] / "private" / "press" / "narration-v6"
SPEED = 1.1


def main() -> None:
    script = json.loads((DIR / "script.json").read_text(encoding="utf-8"))
    names = sys.argv[1:] or list(script)
    tts = TTS()
    voice = tts.get_voice_style("F1")
    asr = WhisperModel("small.en", device="cpu", compute_type="int8")
    for name in names:
        wav, _ = tts.synthesize(script[name]["say"], voice_style=voice, speed=SPEED, lang="en")
        out = DIR / f"{name}.wav"
        tts.save_audio(wav, str(out))
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                    "default=nw=1:nk=1", str(out)], capture_output=True, text=True).stdout)
        segs, _ = asr.transcribe(str(out), beam_size=5)
        print(f"{name} {dur:5.1f}s | {' '.join(s.text.strip() for s in segs)}", flush=True)


if __name__ == "__main__":
    main()
