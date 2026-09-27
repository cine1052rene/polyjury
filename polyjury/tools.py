"""System packages a proof may need, installed in the sandbox only when the code uses them.

A clean python:3.12-slim VM has no ffmpeg and no fonts, so a video script dies on its
first line and the proof never reaches the claim. The list is fixed and installed from
Debian's own mirror: the code under review cannot choose what gets installed.
"""
from __future__ import annotations

import re
from pathlib import Path

FONT_NAME = re.compile(r"[\"']([\w.-]+\.(?:ttf|otf|ttc))[\"']", re.I | re.ASCII)
STAND_IN = "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"

# (words in the code that mean it needs this, apt packages, what the chair is told)
NEEDS = [
    (("ffmpeg", "ffprobe"), ["ffmpeg"], "ffmpeg and ffprobe are on PATH"),
    ((".ttf", ".otf", "truetype", "ImageFont"), ["fonts-nanum", "fonts-dejavu-core"],
     "stand-in fonts: /usr/share/fonts/truetype/nanum/NanumGothic.ttf (has Korean) and "
     "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf; if the code expects a font file that "
     "is missing, copy one of these to that path first"),
]
TIMEOUT = 90  # ffmpeg took 26-70 s from Debian's mirror; fonts about 1 s


def _texts(root: Path, files: list[Path]):
    for rel in files:
        if Path(rel).suffix.lower() in {".py", ".js", ".ts", ".sh"}:
            try:
                yield (root / rel).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue


def needed(root: Path, files: list[Path]) -> list[tuple[list[str], str]]:
    found, texts = [], list(_texts(root, files))
    for words, packages, note in NEEDS:
        if any(w in t for t in texts for w in words):
            found.append((packages, note))
    return found


def packages(root: Path, files: list[Path]) -> list[str]:
    return [p for pkgs, _ in needed(root, files) for p in pkgs]


def bundle_note(root: Path, files: list[Path]) -> str:
    notes = [note for _, note in needed(root, files)]
    return ("### SYSTEM TOOLS installed when the proof runs: " + "; ".join(notes) + "\n") if notes else ""


def apt_step(pkgs: list[str]) -> str:
    return ("(timeout %d sh -c 'apt-get update -qq && DEBIAN_FRONTEND=noninteractive "
            "apt-get install -y -qq --no-install-recommends %s' > /tmp/apt.log 2>&1 "
            "|| echo '[polyjury] installing system tools failed')" % (TIMEOUT, " ".join(pkgs)))


def font_names(root: Path, files: list[Path]) -> list[str]:
    """Font files the code asks for by name, e.g. "GowunDodum-Regular.ttf"."""
    names = {m.group(1) for t in _texts(root, files) for m in FONT_NAME.finditer(t)}
    shipped = {Path(f).name for f in files}
    return sorted(n for n in names if n not in shipped)[:10]


def font_step(names: list[str]) -> str:
    """Put a Korean-capable stand-in where the repository's own fonts/ folder would be."""
    if not names:
        return ""
    cps = " ".join(f"[ -e /work/fonts/{n} ] || cp {STAND_IN} /work/fonts/{n};" for n in names)
    return f"(mkdir -p /work/fonts && {cps} true) 2>/dev/null"


def font_note(names: list[str]) -> str:
    if not names:
        return ""
    return ("### FONTS: the repository does not include " + ", ".join(names) + " (a fresh clone "
            "lacks it: that is an established fact). So that proofs can reach other behaviour, a "
            "stand-in copy of each was placed at /work/fonts/<name>; copy it to any other path the "
            "code expects. To test a claim about the missing font itself, delete the stand-in first.\n")
