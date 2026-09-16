"""환경변수 로딩 및 전역 설정."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"환경변수 {name} 가 비어 있습니다. .env 를 확인하세요.")
    return value


# --- Nebius Token Factory ---------------------------------------------------
NEBIUS_API_KEY = _require("NEBIUS_API_KEY")
NEBIUS_BASE_URL = os.environ.get(
    "NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/"
).strip()

# 두뇌(추론/판단): NVIDIA Nemotron — 해커톤 필수 요건(NVIDIA 오픈 모델 1개 이상)을 이 축으로 충족
TEXT_MODEL = os.environ.get(
    "NEBIUS_TEXT_MODEL", "nvidia/nemotron-3-super-120b-a12b"
).strip()
HEAVY_MODEL = os.environ.get(
    "NEBIUS_HEAVY_MODEL", "nvidia/Nemotron-3-Ultra-550b-a55b"
).strip()

# 눈(장면 서술): 비전 모델
# NOTE: NVIDIA Cosmos3-Super-Reasoner 는 Dedicated 엔드포인트 전용이라
#       서버리스 API 로는 404. 비전은 아래 모델로 처리하고 판단은 Nemotron 이 맡는다.
VISION_MODEL = os.environ.get("NEBIUS_VISION_MODEL", "google/gemma-3-27b-it").strip()
VISION_FALLBACK = os.environ.get(
    "NEBIUS_VISION_FALLBACK", "openbmb/MiniCPM-V-4_5"
).strip()

# --- Tavily -----------------------------------------------------------------
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "").strip()

# --- 기타 -------------------------------------------------------------------
REQUEST_TIMEOUT = float(os.environ.get("NEBIUS_TIMEOUT", "120"))
MAX_RETRIES = int(os.environ.get("NEBIUS_MAX_RETRIES", "1"))
