"""Did the proof actually run the repository's code, or only read it?

The chair labels its own proofs `KIND: dynamic | static`, and a label is not
evidence: a script that greps the source for `regen(` and prints REPRODUCED
called itself dynamic. So the label is checked against the script itself. A
proof counts as a run only if it imports one of the repository's modules, or
executes one of its files (runpy, importlib, subprocess, exec). Re-implementing
a function inside the proof and calling that copy is not a run of the repo.
"""
from __future__ import annotations

import ast
from pathlib import Path, PurePosixPath

# loading a URDF/MJCF into the simulator executes the description the way importing runs code
ROBOT_LOADERS = {"load", "from_file", "from_xml_path", "from_xml_string", "summary", "compare_limits"}
RUNNERS = {"run_path", "run_module", "import_module", "spec_from_file_location",
           "run", "Popen", "call", "check_call", "check_output", "exec", "system"}


def _repo_names(files: list[Path]) -> tuple[set[str], set[str]]:
    """Top-level import names the repository provides, and its file paths."""
    names, paths = set(), set()
    for rel in files:
        p = PurePosixPath(Path(rel).as_posix())
        paths.add(p.as_posix())
        paths.add(p.name)
        parts = list(p.parts)
        if parts and parts[0] in ("src", "app", "lib") and len(parts) > 1:
            parts = parts[1:]  # these folders are on PYTHONPATH too
        if p.suffix == ".py":
            names.add(parts[0] if len(parts) > 1 else p.stem)
    return names, paths


def _call_name(node: ast.Call) -> str:
    f = node.func
    return f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""


def runs_repo_code(script: str, files: list[Path]) -> bool:
    try:
        tree = ast.parse(script)
    except SyntaxError:
        return False
    names, paths = _repo_names(files)
    mentions_file = False
    executes = False
    robot_desc = {p for p in paths if p.lower().endswith((".urdf", ".xml"))}
    loads_robot = mentions_desc = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(a.name.split(".")[0] in names for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and (node.module or "").split(".")[0] in names:
                return True
        elif isinstance(node, ast.Call) and _call_name(node) in RUNNERS | ROBOT_LOADERS:
            executes = executes or _call_name(node) in RUNNERS
            loads_robot = loads_robot or _call_name(node) in ROBOT_LOADERS
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value.replace("\\", "/")
            if any(text.endswith(p) for p in paths) or text.split(".")[0] in names:
                mentions_file = True
            if any(text.endswith(p) for p in robot_desc):
                mentions_desc = True
    return (executes and mentions_file) or (loads_robot and mentions_desc)
