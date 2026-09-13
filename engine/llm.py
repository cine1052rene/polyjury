"""Small helpers around Token Factory chat calls used by the game engine."""
from __future__ import annotations

import json
import re
import time
from typing import Any

import config
from core.nebius_client import get_client

NEMOTRON = config.TEXT_MODEL


def chat(system: str, user: str, *, think: bool = True, model: str | None = None,
         max_tokens: int = 5000, temperature: float = 0.3) -> tuple[str, float]:
    """Run one chat call. Returns (text, seconds)."""
    t0 = time.time()
    text = get_client().chat(user, system=system, model=model or NEMOTRON,
                             temperature=temperature, max_tokens=max_tokens, thinking=think)
    return text, round(time.time() - t0, 2)


def parse_json(text: str) -> Any:
    """Extract the first JSON object/array from a model reply (tolerates code fences)."""
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    body = fence.group(1) if fence else text
    starts = [i for i in (body.find("{"), body.find("[")) if i != -1]
    if not starts:
        return None
    start = min(starts)
    closer = "}" if body[start] == "{" else "]"
    end = body.rfind(closer)
    if end <= start:
        return None
    try:
        return json.loads(body[start:end + 1])
    except json.JSONDecodeError:
        return None
