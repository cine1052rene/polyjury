"""Case files on disk: one JSON per city per day."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = ROOT / "data" / "cases"


def save_case(case: dict) -> Path:
    CASE_DIR.mkdir(parents=True, exist_ok=True)
    path = CASE_DIR / f"{case['id']}.json"
    path.write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_case_by_id(case_id: str) -> dict | None:
    if not case_id.replace("-", "").isalnum():
        return None
    path = CASE_DIR / f"{case_id}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def latest_case(city_id: str) -> dict | None:
    files = sorted(CASE_DIR.glob(f"{city_id}-*.json"))
    return json.loads(files[-1].read_text(encoding="utf-8")) if files else None


def public_view(case: dict) -> dict:
    return {"id": case["id"], "city": case["city"], "city_name": case["city_name"],
            "date": case["date"], **case["public"]}
