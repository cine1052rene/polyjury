"""Nebius Token Factory 호출 래퍼.

OpenAI Python SDK 호환 엔드포인트를 사용한다 (base_url 만 교체).
해커톤 필수 요건인 NVIDIA 오픈 모델(Cosmos 계열)을 기본값으로 쓴다.
"""
from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any, Iterable, Sequence

from openai import OpenAI

import config

__all__ = [
    "NebiusClient",
    "get_client",
    "encode_image",
]

Message = dict[str, Any]


def encode_image(path: str | Path) -> str:
    """로컬 이미지를 data URL 로 변환한다 (Vision 입력용)."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"이미지를 찾을 수 없습니다: {path}")

    mime, _ = mimetypes.guess_type(path.name)
    if mime is None or not mime.startswith("image/"):
        mime = "image/jpeg"

    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{payload}"


class NebiusClient:
    """Token Factory 채팅/비전 호출을 감싼 얇은 래퍼."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        text_model: str | None = None,
        vision_model: str | None = None,
    ) -> None:
        self.text_model = text_model or config.TEXT_MODEL
        self.vision_model = vision_model or config.VISION_MODEL
        self._client = OpenAI(
            api_key=api_key or config.NEBIUS_API_KEY,
            base_url=base_url or config.NEBIUS_BASE_URL,
            timeout=config.REQUEST_TIMEOUT,
            max_retries=config.MAX_RETRIES,
        )

    # -- 모델 목록 ----------------------------------------------------------
    def list_models(self) -> list[str]:
        """사용 가능한 모델 ID 목록."""
        return sorted(m.id for m in self._client.models.list().data)

    def find_models(self, keyword: str) -> list[str]:
        """키워드가 포함된 모델 ID만 추린다 (대소문자 무시)."""
        needle = keyword.lower()
        return [m for m in self.list_models() if needle in m.lower()]

    # -- 텍스트 -------------------------------------------------------------
    def chat(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        thinking: bool | None = None,
    ) -> str:
        messages: list[Message] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self.complete(
            messages, model=model or self.text_model,
            temperature=temperature, max_tokens=max_tokens, thinking=thinking,
        )

    # -- 비전 ---------------------------------------------------------------
    def chat_with_images(
        self,
        prompt: str,
        images: Sequence[str | Path],
        *,
        system: str | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        """이미지 1장 이상 + 텍스트 프롬프트로 추론한다.

        images 는 로컬 경로 또는 http(s)/data URL 을 섞어 넣을 수 있다.
        """
        parts: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for item in images:
            url = str(item)
            if not url.startswith(("http://", "https://", "data:")):
                url = encode_image(url)
            parts.append({"type": "image_url", "image_url": {"url": url}})

        messages: list[Message] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": parts})

        return self.complete(
            messages, model=model or self.vision_model,
            temperature=temperature, max_tokens=max_tokens,
        )

    # -- 공통 ---------------------------------------------------------------
    def complete(
        self,
        messages: Iterable[Message],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        thinking: bool | None = None,
    ) -> str:
        """thinking: Nemotron 추론 모드 on/off (None 이면 모델 기본값).

        생각 모드를 켜면 답 전에 reasoning 토큰을 쓰므로 max_tokens 를 넉넉히 줄 것.
        """
        kwargs: dict[str, Any] = {
            "model": model or self.text_model,
            "messages": list(messages),
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if thinking is not None:
            kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": thinking}}

        response = self._client.chat.completions.create(**kwargs)
        return (response.choices[0].message.content or "").strip()

    @property
    def raw(self) -> OpenAI:
        """필요 시 원본 OpenAI 클라이언트에 직접 접근."""
        return self._client


_singleton: NebiusClient | None = None


def get_client() -> NebiusClient:
    """프로세스 전역 싱글턴."""
    global _singleton
    if _singleton is None:
        _singleton = NebiusClient()
    return _singleton
