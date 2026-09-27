"""The decisive scene of the demo: SO-ARM100's elbow, swept alone from the home pose, drives
the gripper into the shoulder well inside its own joint limit. Rendered with MuJoCo from the
repository's own URDF; the two colliding links turn red the moment the meshes touch.
usage: python render_arm.py URDF OUT.mp4 [--preview frame.png] [--cam az,el,dist,lx,ly,lz] [--still]"""
from __future__ import annotations

import math
import shutil
import subprocess
import sys
from pathlib import Path

import mujoco
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "polyjury"))
import robot_helper as R  # noqa: E402

from build_demo_video import ACC, INK, MUT, font  # noqa: E402

W, H, FPS = 1280, 720, 25
JOINT, PAIR = "elbow_flex", ("gripper_link", "shoulder_link")
SWEEP_S, HOLD_S = 9.0, 3.0
CAM = [60, -18, 0.42, 0.0, 0.0, 0.175]  # azimuth, elevation, distance, lookat xyz
GREY, RED, DIM = (0.78, 0.80, 0.84, 1.0), (0.86, 0.22, 0.22, 1.0), (0.45, 0.47, 0.52, 1.0)


def main() -> None:
    urdf, out = sys.argv[1], Path(sys.argv[2])
    preview = Path(sys.argv[sys.argv.index("--preview") + 1]) if "--preview" in sys.argv else None
    cam_args = [float(x) for x in sys.argv[sys.argv.index("--cam") + 1].split(",")] if "--cam" in sys.argv else CAM
    still = "--still" in sys.argv  # render only the final frame, for choosing a camera
    m = R.load(urdf)
    d = mujoco.MjData(m)
    lo, hi = R.joints(m)[JOINT]
    j = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, JOINT)
    bodies = {mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, b) for b in PAIR}
    onset = R.first_contact(m, JOINT, PAIR)
    m.geom_rgba[:] = GREY
    for g in range(m.ngeom):
        if m.geom_bodyid[g] == 0:
            m.geom_rgba[g] = DIM
    m.vis.global_.offwidth, m.vis.global_.offheight = W, H
    renderer = mujoco.Renderer(m, H, W)
    cam = mujoco.MjvCamera()
    cam.type = mujoco.mjtCamera.mjCAMERA_FREE
    cam.azimuth, cam.elevation, cam.distance = cam_args[:3]
    cam.lookat[:] = cam_args[3:6]
    opt = mujoco.MjvOption()

    frames = Path(str(out) + ".frames")
    shutil.rmtree(frames, ignore_errors=True)
    frames.mkdir(parents=True)
    n_sweep, n_hold = int(SWEEP_S * FPS), int(HOLD_S * FPS)
    big, small = font(44, True), font(26)
    for i in ([n_sweep + n_hold - 1] if still else range(n_sweep + n_hold)):
        s = min(i / n_sweep, 1.0)
        q = hi * (1 - math.cos(s * math.pi)) / 2  # ease in-out
        d.qpos[:] = 0
        d.qpos[m.jnt_qposadr[j]] = q
        mujoco.mj_forward(m, d)
        hit = any({m.geom_bodyid[c.geom1], m.geom_bodyid[c.geom2]} == bodies and c.dist < -0.003
                  for c in d.contact[:d.ncon])
        for g in range(m.ngeom):
            if m.geom_bodyid[g] in bodies:
                m.geom_rgba[g] = RED if hit else GREY
        renderer.update_scene(d, cam, opt)
        img = Image.fromarray(renderer.render())
        dr = ImageDraw.Draw(img)
        deg = math.degrees(q)
        dr.text((48, 40), f"{JOINT}  {deg:5.1f}°", font=big, fill=INK)
        dr.text((48, 100), f"joint limit in the repository: {math.degrees(hi):.1f}°", font=small, fill=MUT)
        if hit:
            dr.text((48, 140), f"gripper inside the shoulder since {math.degrees(onset):.1f}°  "
                    f"— a limit the file allows", font=small, fill=(220, 70, 70))
        else:
            dr.text((48, 140), "every other joint at its home position", font=small, fill=MUT)
        if preview and i == n_sweep + n_hold - 1:
            img.save(preview)
        img.save(frames / f"f{i:04d}.png")
    if still:
        shutil.rmtree(frames, ignore_errors=True)
        return
    subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", str(frames / "f%04d.png"), "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-crf", "20", str(out)], check=True, capture_output=True)
    shutil.rmtree(frames, ignore_errors=True)
    print(f"{out}: onset {onset} rad = {math.degrees(onset):.1f} deg, limit {math.degrees(hi):.1f} deg")


if __name__ == "__main__":
    main()
