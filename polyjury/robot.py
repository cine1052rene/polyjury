"""Robot descriptions (URDF, MJCF) as something Polyjury can review and prove by simulation.

A URDF is code in the sense that matters here: a wrong joint limit ships a robot that drives
itself into its own frame, and nobody finds out until the hardware does. Jurors read the
description like any source file; the proof loads it in MuJoCo inside the sandbox and moves
the joints. The meshes the description references are uploaded with it, capped in size.
"""
from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

DESC_EXT = {".urdf", ".xml"}
MESH_EXT = {".stl", ".obj"}
MAX_DESC_BYTES = 160_000
MAX_MESH_BYTES = 6_000_000
MAX_MESH_TOTAL = 40_000_000
MAX_DESCS = 6  # a ROS repo can hold dozens: keep room for the code
PACKAGES = ["mujoco", "trimesh", "manifold3d", "scipy", "numpy"]
INSTALL_TIMEOUT = 150  # mujoco alone took 11 s in the sandbox; scipy is the slow one
HELPER = Path(__file__).with_name("robot_helper.py")
REMOTE_HELPER = "/work/_pj_robot.py"
MESH_REF = re.compile(r"""(?:filename|file)\s*=\s*["']([^"']+\.(?:stl|obj))["']""", re.I)
MESHDIR = re.compile(r"""meshdir\s*=\s*["']([^"']*)["']""")


def kind(head: str) -> str:
    """'urdf', 'mjcf' or '' from the first bytes of a file."""
    if re.search(r"<robot[\s>]", head):
        return "urdf"
    if re.search(r"<mujoco[\s>]", head):
        return "mjcf"
    return ""


def is_description(path: Path) -> bool:
    if path.suffix.lower() not in DESC_EXT:
        return False
    try:
        if not 0 < path.stat().st_size <= MAX_DESC_BYTES:
            return False
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            return bool(kind(fh.read(4000)))
    except OSError:
        return False


def descriptions(root: Path, files: list[Path]) -> list[Path]:
    return [rel for rel in files if is_description(root / rel)]


def _resolve(root: Path, desc: Path, ref: str, by_name: dict[str, list[Path]]) -> Path | None:
    """The repository file a mesh reference points at, relative to root."""
    text = (root / desc).read_text(encoding="utf-8", errors="replace")
    local = ref.split("://", 1)[1].split("/", 1)[-1] if "://" in ref else ref
    bases = [desc.parent]
    m = MESHDIR.search(text)
    if m:
        bases.insert(0, desc.parent / m.group(1))
    for base in bases:
        cand = PurePosixPath((base / local).as_posix())
        parts: list[str] = []
        for part in cand.parts:  # normalise "../" without touching the disk
            if part == "..":
                if not parts:
                    break
                parts.pop()
            elif part != ".":
                parts.append(part)
        rel = Path(*parts) if parts else None
        if rel and (root / rel).is_file():
            return rel
    hits = by_name.get(PurePosixPath(local).name.lower(), [])
    return min(hits, key=lambda p: len(p.parts)) if hits else None


def meshes(root: Path, descs: list[Path]) -> list[Path]:
    """Mesh files the descriptions reference, smallest first until the cap."""
    if not descs:
        return []
    by_name: dict[str, list[Path]] = {}
    for p in root.rglob("*"):
        if p.suffix.lower() in MESH_EXT and p.is_file():
            by_name.setdefault(p.name.lower(), []).append(p.relative_to(root))
    wanted: set[Path] = set()
    for desc in descs:
        text = (root / desc).read_text(encoding="utf-8", errors="replace")
        for ref in set(MESH_REF.findall(text)):
            rel = _resolve(root, desc, ref, by_name)
            if rel:
                wanted.add(rel)
    sized = sorted(((root / rel).stat().st_size, rel.as_posix(), rel) for rel in wanted)
    out, total = [], 0
    for size, _, rel in sized:
        if size <= MAX_MESH_BYTES and total + size <= MAX_MESH_TOTAL:
            out.append(rel)
            total += size
    return out


def note(root: Path, files: list[Path]) -> str:
    """What the chair is told when the repository describes a robot. Jurors never see it."""
    descs = descriptions(root, files)
    if not descs:
        return ""
    names = ", ".join(d.as_posix() for d in descs[:12])
    text = (
        "### ROBOT SIMULATION: robot descriptions found (" + names + "). When the proof runs, "
        "mujoco, trimesh, manifold3d, scipy and numpy are installed, the referenced meshes are "
        "present, and a tested helper is importable as `import _pj_robot as R`:\n"
        "#   m = R.load(path)  (URDF or MJCF; fixes package:// mesh paths)   R.joints(m) -> {name:(lo,hi)}\n"
        "#   R.home(m) / R.contacts(m, {joint: value}) -> [(depth_mm, link_a, link_b)] (parent-child and <3 mm ignored)\n"
        "#   R.sweep(m, joint) -> [(value, new contacts)] moving ONE joint from home through its limits\n"
        "#   R.first_contact(m, joint, (link_a, link_b), toward='upper'|'lower') -> onset value or None\n"
        "#   R.exact_overlap(m, pose, link_a, link_b) -> {hull_mm3, exact_mm3, real, watertight}\n"
        "#   R.compare_limits(path_a, path_b) -> joints whose limits differ\n"
        "# A collision somewhere in the full joint grid is NORMAL for an arm and proves nothing. Evidence "
        "of a defect is: a collision at the home pose; a collision one joint reaches alone from home "
        "inside its own limits (confirm with exact_overlap, since MuJoCo uses convex hulls); two files "
        "for the same robot that disagree; or a file that fails to load. A claim that a file fails to load, or "
        "that two files clash when combined, is decided only by R.load() of the file that combines "
        "them, never by comparing their text. An attribute value (a scale, a missing tag, a shared "
        "name) is not evidence of its consequence: MEASURE the consequence after R.load() - a link's "
        "real size in metres (mesh vertex extents times the scale, or model.geom_size), a load error, "
        "NaN or a warning after 1000 mujoco.mj_step calls - and answer NOT_REPRODUCED when it does "
        "not happen. Mesh files are often in millimetres, so scale 0.001 is usually correct. "
        "Print the joint value, the "
        "links, depth and the exact overlap volume.")
    # one line: the jurors' filter drops sandbox notes line by line
    return text.replace("\n#", " |").replace("\n", " ") + "\n"


def packages(root: Path, files: list[Path]) -> list[str]:
    return list(PACKAGES) if descriptions(root, files) else []


def helper_source() -> bytes:
    return HELPER.read_bytes()


# ---- the simulator's own check -------------------------------------------------------------
# Jurors read a URDF as text, and a collision is geometry: on SO-ARM100 no juror found that
# elbow_flex drives the gripper into the shoulder, which one simulated sweep shows. So when
# the findings touch a robot description, Polyjury adds this check itself. Its script is a
# fixed template, rebuilt on the server every time: a client can never send code to run.
SIM_MODEL = "polyjury-simulator"
SIM_TITLE = "Simulation check: can one joint, moved inside its own limits, drive the robot into itself?"
SIM_TEMPLATE = '''import math
import _pj_robot as R

PATH = {path!r}
try:
    m = R.load(PATH)
except Exception as exc:
    print("could not load", PATH, "->", type(exc).__name__, str(exc)[:300])
    print("VERDICT: INCONCLUSIVE")
    raise SystemExit
lims = R.joints(m)
print(PATH, "loads:", m.nbody, "bodies,", len(lims), "joints")
home = R.home(m)
print("home pose (all joints 0):", home[:5] if home else "no penetrating contacts")
found = list(home)
for name, (lo, hi) in lims.items():
    if not (math.isfinite(lo) and math.isfinite(hi)):
        continue
    worst = {{}}
    for value, hits in R.sweep(m, name, 41):
        for depth, a, b in hits:
            if depth > worst.get((a, b), (0, 0))[0]:
                worst[(a, b)] = (depth, value)
    if not worst:
        print(f"  {{name}}: clear over {{lo:+.3f}}..{{hi:+.3f}} rad")
        continue
    for (a, b), (depth, value) in sorted(worst.items(), key=lambda kv: -kv[1][0])[:3]:
        side = "upper" if value > 0 else "lower"
        onset = R.first_contact(m, name, (a, b), toward=side)
        exact = R.exact_overlap(m, {{name: value}}, a, b)
        real = exact.get("real", True)  # primitive shapes: MuJoCo's contact is already exact
        print(f"  {{name}} = {{value:+.3f}} rad (limit {{lo:+.3f}}..{{hi:+.3f}}): {{a}} hits {{b}}, "
              f"hull depth {{depth}} mm, first contact at {{onset}} rad, exact meshes {{exact}}")
        if real:
            found.append((name, value, a, b, onset, exact))
print("defects:", len(found))
print("VERDICT: REPRODUCED" if found else "VERDICT: NOT_REPRODUCED")
'''


def sim_claims(findings: list[dict]) -> list[dict]:
    """One simulator claim for the robot description the jurors discussed most."""
    count: dict[str, int] = {}
    for f in findings:
        name = str(f.get("file", "")).strip().split(" ")[0].strip(",;()")
        if name.lower().endswith((".urdf", ".xml")) and ".." not in name:
            count[name] = count.get(name, 0) + 1
    if not count:
        return []
    best = max(count, key=lambda n: (count[n], n.lower().endswith(".urdf"), -len(n)))
    return [{"title": SIM_TITLE, "file": best, "where": "every joint, swept alone from the home pose",
             "severity": "high", "models": [SIM_MODEL],
             "what_breaks": "The robot can be commanded into its own body without breaking any joint "
                            "limit: on real hardware that strips gears or cracks printed parts."}]


def sim_script(root: Path, files: list[Path], file: str) -> str:
    """The fixed proof, or '' when the file is not a robot description in this repository."""
    rel = Path(file.replace("\\", "/"))
    if rel not in [Path(f) for f in files] or not is_description(root / rel):
        return ""
    return SIM_TEMPLATE.format(path=rel.as_posix())
