"""Polyjury as an MCP tool, for Claude Code, Codex or any MCP client.

One file, standard library only. It drives the public Polyjury site step by step,
exactly like the web page does, so your assistant gets the same verdict you would:
three jurors review, Nemotron merges, every claim is proved in a Nebius Sandbox,
and only what reproduced is marked confirmed.

    Claude Code:  claude mcp add polyjury -- python /path/to/polyjury_mcp.py
    Codex:        see README ("Use it from your AI") for the config.toml block

Try it without an assistant:
    python polyjury_mcp.py --once https://github.com/owner/repo/tree/main/some/folder
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = os.environ.get("POLYJURY_URL", "https://polyjury.vercel.app").rstrip("/")
VERSION = "0.1.0"
TOOL = {
    "name": "polyjury_verify",
    "description": (
        "Cross-check a public GitHub repository, or one folder of it, with a jury of open models. "
        "Three models review the code separately, NVIDIA Nemotron merges their claims and writes a "
        "proof script for each, and every script runs in a disposable Nebius Sandbox. Returns each "
        "claim as CONFIRMED (reproduced by running it), FALSE ALARM, or NEEDS A HUMAN, with the run's "
        "own output as evidence, plus a fix prompt covering confirmed defects only. Takes 2-4 minutes. "
        "Only confirmed claims should be treated as real bugs."),
    "inputSchema": {
        "type": "object",
        "properties": {"target": {"type": "string", "description":
                                  "https://github.com/owner/repo or https://github.com/owner/repo/tree/<branch>/<folder>"}},
        "required": ["target"],
    },
}
LABEL = {"REPRODUCED": "CONFIRMED", "NOT_REPRODUCED": "FALSE ALARM", "UNVERIFIED": "NEEDS A HUMAN"}


def _post(path: str, body: dict, timeout: int = 320) -> dict:
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json", "user-agent": f"polyjury-mcp/{VERSION}"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        try:
            detail = json.loads(detail).get("detail", detail)
        except ValueError:
            pass
        raise RuntimeError(f"{path} failed ({exc.code}): {detail}") from exc


def verify(target: str, progress=lambda step, total, msg: None) -> str:
    models = json.loads(urllib.request.urlopen(BASE + "/api/models", timeout=60).read())["reviewers"]
    progress(1, 5, "fetching the code")
    repo = _post("/api/collect", {"target": target})
    bundle = repo["bundle"]

    progress(2, 5, f"{len(models)} jurors reading {len(repo['files'])} files")
    with ThreadPoolExecutor(max_workers=len(models)) as pool:
        reviews = list(pool.map(lambda m: _safe(lambda: _post("/api/review", {"bundle": bundle, "model": m})), models))
    findings = [f for r in reviews for f in (r.get("findings") or [])]
    if not findings:
        return f"No juror returned usable findings for {repo['name']}."

    progress(3, 5, f"Nemotron merging {len(findings)} findings")
    claims = _post("/api/merge", {"findings": findings})["claims"]

    progress(4, 5, f"proving {len(claims)} claims in Nebius Sandboxes")
    with ThreadPoolExecutor(max_workers=4) as pool:
        proved = list(pool.map(lambda c: _safe(lambda: _post("/api/prove", {"target": target, "bundle": bundle, "claim": c}),
                                               {**c, "verdict": "UNVERIFIED", "evidence": "the prove call failed"}), claims))
    progress(5, 5, "writing the verdict")
    prompt = _safe(lambda: _post("/api/fix-prompt", {"findings": proved}), {}).get("prompt", "")
    return _report(repo, len(models), len(findings), proved, prompt)


def _safe(call, fallback=None):
    try:
        return call()
    except Exception as exc:  # noqa: BLE001
        return fallback if fallback is not None else {"error": str(exc), "findings": []}


def _report(repo: dict, jurors: int, n_findings: int, claims: list[dict], prompt: str) -> str:
    ran = [c for c in claims if c.get("verdict") == "REPRODUCED" and c.get("proof_kind") == "dynamic"]
    lines = [f"# Polyjury verdict: {repo['name']}",
             f"{n_findings} findings from {jurors} jurors became {len(claims)} claims; "
             f"{len(ran)} reproduced by actually running the code.",
             "Treat only CONFIRMED claims as real defects. NEEDS A HUMAN means the check itself could not decide.", ""]
    order = {"REPRODUCED": 0, "UNVERIFIED": 1, "NOT_REPRODUCED": 2}
    for c in sorted(claims, key=lambda c: order.get(c.get("verdict"), 3)):
        label = LABEL.get(c.get("verdict"), c.get("verdict"))
        if c.get("verdict") == "REPRODUCED" and c.get("proof_kind") != "dynamic":
            label = "LIKELY (read, not run)"
        lines += [f"## [{label}] {c.get('title', '')}",
                  f"- where: {c.get('file', '')} {c.get('where') or ''}".rstrip(),
                  f"- ran in: {c.get('runner') or 'not run'}",
                  f"- what the run shows: {c.get('what_it_proves') or ''}",
                  "```", (c.get("evidence") or "no output")[-1500:], "```", ""]
    if prompt:
        lines += ["## Fix prompt (confirmed defects only)", prompt]
    return "\n".join(lines)


# ---------- MCP over stdio: newline-delimited JSON-RPC ----------

def _send(msg: dict) -> None:
    sys.stdout.buffer.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def _handle(msg: dict) -> None:
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:  # a notification, e.g. notifications/initialized
        return
    if method == "initialize":
        version = (msg.get("params") or {}).get("protocolVersion") or "2025-06-18"
        _send({"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": version, "capabilities": {"tools": {}},
            "serverInfo": {"name": "polyjury", "version": VERSION}}})
    elif method == "tools/list":
        _send({"jsonrpc": "2.0", "id": mid, "result": {"tools": [TOOL]}})
    elif method == "tools/call":
        params = msg.get("params") or {}
        token = (params.get("_meta") or {}).get("progressToken")

        def progress(step, total, text):
            if token is not None:
                _send({"jsonrpc": "2.0", "method": "notifications/progress",
                       "params": {"progressToken": token, "progress": step, "total": total, "message": text}})
            print(f"[polyjury] {text}", file=sys.stderr, flush=True)

        try:
            if params.get("name") != TOOL["name"]:
                raise RuntimeError(f"unknown tool {params.get('name')}")
            text, error = verify((params.get("arguments") or {}).get("target", ""), progress), False
        except Exception as exc:  # noqa: BLE001
            text, error = f"Polyjury could not finish: {exc}", True
        _send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}], "isError": error}})
    elif method == "ping":
        _send({"jsonrpc": "2.0", "id": mid, "result": {}})
    else:
        _send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}})


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--once":
        sys.stdout.reconfigure(encoding="utf-8")
        print(verify(sys.argv[2], lambda s, t, m: print(f"[{s}/{t}] {m}", file=sys.stderr, flush=True)))
        return
    for raw in sys.stdin.buffer:
        line = raw.decode("utf-8", "replace").strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        # a verdict takes minutes: answer pings and other requests meanwhile
        if msg.get("method") == "tools/call":
            ThreadPoolExecutor(max_workers=1).submit(_handle, msg)
        else:
            _handle(msg)


if __name__ == "__main__":
    main()
