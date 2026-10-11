"""Write the v5 CC subtitle tracks (English and Korean) timed to the actual voice.

Each narration clip is transcribed with word timestamps (faster-whisper); every caption chunk in
narration-v5/captions.json gets the span of its share of the spoken words, offset by where the
clip starts in the video (build-v5/timeline.json). Output: polyjury-demo-v5.en.srt / .ko.srt.
"""
from __future__ import annotations

import json
from pathlib import Path

from faster_whisper import WhisperModel

PRESS = Path(__file__).resolve().parents[1] / "private" / "press"
VOICE = PRESS / "narration-v5"


def stamp(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def main() -> None:
    starts = json.loads((PRESS / "build-v5" / "timeline.json").read_text(encoding="utf-8"))["starts"]
    chunks = json.loads((VOICE / "captions.json").read_text(encoding="utf-8"))
    asr = WhisperModel("small.en", device="cpu", compute_type="int8")
    cues: list[tuple[float, float, str, str]] = []
    for clip, items in chunks.items():
        segs, _ = asr.transcribe(str(VOICE / f"{clip}.wav"), word_timestamps=True, beam_size=5)
        words = [w for s in segs for w in s.words]
        counts = [len(en.split()) for en, _ in items]
        total, done = sum(counts), 0
        for (en, ko), n in zip(items, counts):
            a = round(done / total * len(words))
            done += n
            b = max(a, round(done / total * len(words)) - 1)
            t0, t1 = words[a].start, words[min(b, len(words) - 1)].end
            cues.append((starts[clip] + t0, starts[clip] + t1 + 0.25, en, ko))
    for lang, i in (("en", 2), ("ko", 3)):
        out = PRESS / f"polyjury-demo-v5.{lang}.srt"
        lines = []
        for n, cue in enumerate(cues, 1):
            end = min(cue[1], cues[n][0] - 0.05) if n < len(cues) else cue[1]
            lines += [str(n), f"{stamp(cue[0])} --> {stamp(end)}", cue[i], ""]
        out.write_text("\n".join(lines), encoding="utf-8")
        print(out, len(cues), "cues")


if __name__ == "__main__":
    main()
