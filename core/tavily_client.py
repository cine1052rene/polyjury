"""Tavily 검색 래퍼.

설계 원칙: Tavily 는 "항상 부르는 도구"가 아니라 **모델이 스스로 근거가 부족하다고
판단했을 때만** 부르는 도구다. 매 요청마다 검색하면 비용·지연만 늘고 에이전트가 아니다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tavily import TavilyClient as _TavilySDK

import config

__all__ = ["SearchResult", "TavilySearch", "get_search"]


@dataclass
class SearchResult:
    query: str
    answer: str | None
    sources: list[dict[str, Any]] = field(default_factory=list)

    def as_citations(self, limit: int = 3) -> str:
        """Nemotron 에 되먹일 인용 블록으로 직렬화."""
        lines = []
        for s in self.sources[:limit]:
            title = (s.get("title") or "").strip()
            url = (s.get("url") or "").strip()
            snippet = " ".join((s.get("content") or "").split())[:400]
            lines.append(f"- {title} <{url}>\n  {snippet}")
        return "\n".join(lines) if lines else "(no sources)"


class TavilySearch:
    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or config.TAVILY_API_KEY
        if not key:
            raise RuntimeError("TAVILY_API_KEY 가 비어 있습니다. .env 를 확인하세요.")
        self._client = _TavilySDK(api_key=key)

    def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        depth: str = "advanced",
        include_answer: bool = True,
        include_domains: list[str] | None = None,
    ) -> SearchResult:
        kwargs: dict[str, Any] = {
            "query": query,
            "max_results": max_results,
            "search_depth": depth,
            "include_answer": include_answer,
        }
        if include_domains:
            kwargs["include_domains"] = include_domains

        raw = self._client.search(**kwargs)
        return SearchResult(
            query=query,
            answer=raw.get("answer"),
            sources=raw.get("results", []) or [],
        )

    def verify_claims(self, claims: list[str], **kwargs: Any) -> dict[str, SearchResult]:
        """[VERIFY] 로 표시된 주장들만 선별 검증한다."""
        return {c: self.search(c, **kwargs) for c in claims}


_singleton: TavilySearch | None = None


def get_search() -> TavilySearch:
    global _singleton
    if _singleton is None:
        _singleton = TavilySearch()
    return _singleton
