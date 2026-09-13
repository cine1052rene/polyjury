"""현장 사진 전처리.

실측 결과: 산업 현장 사진은 대부분 저조도다. 원본 그대로 VLM에 넣으면
가연물(천막·보온재 등)을 통째로 놓친다. 감마 보정으로 암부를 끌어올리면
같은 모델·같은 프롬프트에서 탐지에 성공한다. 전처리는 선택이 아니라 필수 단계.
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance

DEFAULT_GAMMA = 0.45
DEFAULT_CONTRAST = 1.15


def enhance(
    src: str | Path | Image.Image,
    gamma: float = DEFAULT_GAMMA,
    contrast: float = DEFAULT_CONTRAST,
) -> Image.Image:
    """암부를 끌어올리되 하이라이트(불꽃)는 포화시키지 않는다."""
    im = src if isinstance(src, Image.Image) else Image.open(src)
    im = im.convert("RGB")
    arr = np.asarray(im, dtype=np.float32) / 255.0
    arr = np.clip(arr**gamma, 0.0, 1.0)
    out = Image.fromarray((arr * 255).astype("uint8"))
    if contrast != 1.0:
        out = ImageEnhance.Contrast(out).enhance(contrast)
    return out


def mean_luma(src: str | Path | Image.Image) -> float:
    """평균 밝기(0~1). 전처리 필요 여부 판단용."""
    im = src if isinstance(src, Image.Image) else Image.open(src)
    return float(np.asarray(im.convert("L"), dtype=np.float32).mean() / 255.0)


def auto_enhance(src: str | Path | Image.Image, threshold: float = 0.35) -> Image.Image:
    """어두운 사진만 보정한다. 밝은 사진은 원본 유지."""
    im = src if isinstance(src, Image.Image) else Image.open(src)
    im = im.convert("RGB")
    return enhance(im) if mean_luma(im) < threshold else im


def to_jpeg_bytes(im: Image.Image, quality: int = 92) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()
