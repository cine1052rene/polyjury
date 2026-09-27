"""Robot-description checks a proof can call: uploaded to the sandbox as /work/_pj_robot.py.

Written once and tested, so a proof about a URDF or MJCF file does not have to reinvent
contact filtering or mesh booleans in 30 seconds of generated code. Standard library plus
mujoco, numpy, trimesh and manifold3d (installed only when robot files are present).

Lessons baked in (measured on TheRobotStudio SO-ARM100, 2026-09-27):
- A full joint-limit grid always finds self-collisions on a 6-DOF arm. That is normal: real
  arms rely on the controller. A defect is a collision at the home pose, or one that a SINGLE
  joint reaches from home inside its own limits, or two descriptions that disagree.
- MuJoCo collides meshes as convex hulls, so a hull contact may not be real. exact_overlap()
  re-tests the pose with the actual triangles.
- Parent-child links touch at the joint by design and are ignored, as are contacts under 3 mm.
"""
from __future__ import annotations

import re
from pathlib import Path

import mujoco
import numpy as np

DEPTH_MM = 3.0
MESH_REF = re.compile(r"""(?:filename|file)\s*=\s*["']([^"']+\.(?:stl|obj|msh))["']""", re.I)


def _find(root: Path, name: str) -> Path | None:
    hits = sorted(root.rglob(name), key=lambda p: len(p.parts))
    return hits[0] if hits else None


def load(path: str) -> mujoco.MjModel:
    """Compile a URDF or MJCF file. Mesh paths that do not resolve (package://pkg/..., or a
    folder the repository keeps elsewhere) are looked up by file name under /work."""
    p = Path(path).resolve()
    text = original = p.read_text(encoding="utf-8", errors="replace")
    urdf = p.suffix.lower() == ".urdf" or "<robot" in text[:2000]
    base = p.parent
    if not urdf:
        m = re.search(r"""meshdir\s*=\s*["']([^"']*)["']""", text)
        base = p.parent / m.group(1) if m else p.parent
    work = Path("/work") if Path("/work").is_dir() else p.parent
    for ref in set(MESH_REF.findall(text)):
        local = ref.split("://", 1)[1].split("/", 1)[-1] if "://" in ref else ref
        if (base / local).is_file():
            continue
        found = _find(work, Path(local).name)
        if found:
            text = text.replace(f'"{ref}"', f'"{found.as_posix()}"').replace(f"'{ref}'", f"'{found.as_posix()}'")
    if text != original:  # includes and meshdir stay relative to the original folder
        p = p.with_name(p.stem + ".pj" + p.suffix)
        p.write_text(text, encoding="utf-8")
    spec = mujoco.MjSpec.from_file(str(p))
    if urdf:
        spec.meshdir = str(p.parent)  # URDF mesh paths are relative to the file
        spec.compiler.discardvisual = True
    return spec.compile()


def joints(m) -> dict[str, tuple[float, float]]:
    """Hinge and slide joints with their limits (inf when unlimited)."""
    out = {}
    for j in range(m.njnt):
        if int(m.jnt_type[j]) in (int(mujoco.mjtJoint.mjJNT_HINGE), int(mujoco.mjtJoint.mjJNT_SLIDE)):
            name = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, j) or f"joint{j}"
            lim = (float(m.jnt_range[j][0]), float(m.jnt_range[j][1])) if m.jnt_limited[j] else (-np.inf, np.inf)
            out[name] = lim
    return out


def _jid(m, name: str) -> int:
    j = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, name)
    if j < 0:
        raise KeyError(f"no joint {name!r}; joints are {list(joints(m))}")
    return j


def _pose(m, d, pose: dict[str, float]) -> None:
    d.qpos[:] = m.qpos0
    for name, v in pose.items():
        d.qpos[m.jnt_qposadr[_jid(m, name)]] = v
    mujoco.mj_forward(m, d)


def _body(m, b: int) -> str:
    return mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, b) or f"body{b}"


def contacts(m, pose: dict[str, float] | None = None) -> list[tuple[float, str, str]]:
    """Penetrating contacts between links that are not parent and child, one per pair:
    [(depth_mm, body_a, body_b)], deepest first. pose maps joint name -> value; others at home."""
    d = mujoco.MjData(m)
    _pose(m, d, pose or {})
    out: dict[tuple[str, str], float] = {}
    for c in d.contact[:d.ncon]:
        b1, b2 = m.geom_bodyid[c.geom1], m.geom_bodyid[c.geom2]
        if b1 == b2 or m.body_parentid[b1] == b2 or m.body_parentid[b2] == b1 or -c.dist * 1000 < DEPTH_MM:
            continue
        pair = tuple(sorted((_body(m, b1), _body(m, b2))))
        out[pair] = max(out.get(pair, 0.0), round(-float(c.dist) * 1000, 1))
    return sorted(((v, a, b) for (a, b), v in out.items()), reverse=True)


def home(m) -> list[tuple[float, str, str]]:
    return contacts(m, {})


def sweep(m, joint: str, steps: int = 41) -> list[tuple[float, list]]:
    """Move ONE joint through its limits from home. Returns [(value, new contacts)] for every
    setting where it hits something that was not already touching at home."""
    lo, hi = joints(m)[joint]
    if not np.isfinite(lo) or not np.isfinite(hi):
        lo, hi = -np.pi, np.pi
    at_home = {(a, b) for _, a, b in home(m)}
    hits = []
    for v in np.linspace(lo, hi, steps):
        new = [c for c in contacts(m, {joint: float(v)}) if (c[1], c[2]) not in at_home]
        if new:
            hits.append((round(float(v), 4), new))
    return hits


def first_contact(m, joint: str, pair: tuple[str, str] | None = None, toward: str = "upper",
                  tol: float = 0.002) -> float | None:
    """Bisect for the joint value (moving from 0 toward its upper or lower limit) where a new
    hull contact first appears. None if that side stays clear."""
    lo, hi = joints(m)[joint]
    end = hi if toward == "upper" else lo
    at_home = {(a, b) for _, a, b in home(m)}

    def hit(v: float) -> bool:
        return any((c[1], c[2]) not in at_home and (pair is None or {c[1], c[2]} == set(pair))
                   for c in contacts(m, {joint: v}))
    if not hit(end):
        return None
    a, b = 0.0, end
    while abs(b - a) > tol:
        mid = (a + b) / 2
        a, b = (a, mid) if hit(mid) else (mid, b)
    return round(b, 4)


def _body_mesh(m, d, name: str):
    import trimesh
    b = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, name)
    parts = []
    for g in range(m.ngeom):
        if m.geom_bodyid[g] != b or int(m.geom_type[g]) != int(mujoco.mjtGeom.mjGEOM_MESH):
            continue
        if m.geom_contype[g] == 0 and m.geom_conaffinity[g] == 0:
            continue
        k = m.geom_dataid[g]
        v = m.mesh_vert[m.mesh_vertadr[k]:m.mesh_vertadr[k] + m.mesh_vertnum[k]]
        f = m.mesh_face[m.mesh_faceadr[k]:m.mesh_faceadr[k] + m.mesh_facenum[k]]
        parts.append(trimesh.Trimesh(v @ d.geom_xmat[g].reshape(3, 3).T + d.geom_xpos[g], f, process=True))
    return trimesh.util.concatenate(parts) if parts else None


def _solid(t):
    import manifold3d as mf
    return mf.Manifold(mf.Mesh(vert_properties=np.asarray(t.vertices, np.float32),
                               tri_verts=np.asarray(t.faces, np.uint32)))


def exact_overlap(m, pose: dict[str, float], body_a: str, body_b: str) -> dict:
    """Is a hull contact real? Boolean intersection volume (mm^3) of the two links' actual
    collision meshes, and of their convex hulls, at this pose. 'real' is True above 1 mm^3.
    watertight=False means the mesh has holes and the exact volume is approximate."""
    d = mujoco.MjData(m)
    _pose(m, d, pose)
    A, B = _body_mesh(m, d, body_a), _body_mesh(m, d, body_b)
    if A is None or B is None:
        return {"error": "one of the links has no collision mesh (primitive shapes: trust contacts())"}
    hull = (_solid(A.convex_hull) ^ _solid(B.convex_hull)).volume() * 1e9
    exact = (_solid(A) ^ _solid(B)).volume() * 1e9
    return {"hull_mm3": round(hull, 1), "exact_mm3": round(exact, 1), "real": exact > 1.0,
            "watertight": bool(A.is_watertight and B.is_watertight)}


def compare_limits(path_a: str, path_b: str, tol: float = 1e-3) -> list[str]:
    """Joints whose limits differ between two descriptions of the same robot."""
    a, b = joints(load(path_a)), joints(load(path_b))
    out = []
    for k in sorted(set(a) | set(b)):
        if k not in a or k not in b:
            out.append(f"{k}: only in {'second' if k not in a else 'first'} file")
        elif max(abs(a[k][0] - b[k][0]), abs(a[k][1] - b[k][1])) > tol:
            out.append(f"{k}: {a[k][0]:+.4f}..{a[k][1]:+.4f} vs {b[k][0]:+.4f}..{b[k][1]:+.4f}")
    return out


def summary(path: str) -> None:
    """Print the joints, home-pose contacts and each joint's single-sweep result."""
    m = load(path)
    print(f"{path}: {m.nbody} bodies, {m.ngeom} geoms, joints {joints(m)}")
    print(f"home pose contacts: {home(m)[:5]}")
    for name in joints(m):
        hits = sweep(m, name, 21)
        print(f"  {name}: " + (f"new contact at {len(hits)}/21 settings, first {hits[0]}" if hits else "clear"))
