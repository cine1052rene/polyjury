"""Anti-guessing: evidence must come from an in-game search, and the player must quote it.

Search results are signed by the server (HMAC). The accusation endpoint only accepts evidence
carrying a valid signature for the same city, plus a sentence that really appears in that source.
Stateless, so it works across serverless instances.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time

import config  # noqa: F401  (loads .env)

TOKEN_TTL = 24 * 3600
MIN_QUOTE_CHARS = 15       # after removing spaces and markdown
MIN_REASON_CHARS = 10
QUOTE_MATCH = 0.9

_SECRET = os.environ.get("FACTDUNIT_SECRET", "").encode() or secrets.token_bytes(32)


class EvidenceError(ValueError):
    """Raised with a stable code the front end can translate."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign_result(city_id: str, item: dict) -> str:
    payload = {"c": city_id, "u": item["url"], "t": item.get("title", ""), "p": item.get("published"),
               "s": item.get("text", ""), "i": int(time.time())}
    body = _b64(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
    sig = hmac.new(_SECRET, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_token(token: str, city_id: str) -> dict:
    try:
        body, sig = token.rsplit(".", 1)
    except (AttributeError, ValueError):
        raise EvidenceError("evidence_invalid", "Evidence must come from the in-game search.") from None
    expected = hmac.new(_SECRET, body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise EvidenceError("evidence_invalid", "Evidence must come from the in-game search.")
    payload = json.loads(_unb64(body))
    if payload.get("c") != city_id:
        raise EvidenceError("evidence_city", "This evidence was found while investigating another city.")
    if time.time() - int(payload.get("i", 0)) > TOKEN_TTL:
        raise EvidenceError("evidence_expired", "This evidence is too old. Search again.")
    return {"url": payload["u"], "title": payload.get("t", ""), "published": payload.get("p"),
            "snippet": payload.get("s", "")}


def _norm(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text or "")
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_`#>|“”\"'‘’·…]", "", text)
    return re.sub(r"\s+", "", text).lower()


def quote_overlap(quote: str, page: str, n: int = 5) -> float:
    q, p = _norm(quote), _norm(page)
    grams = {q[i:i + n] for i in range(max(0, len(q) - n + 1))}
    return round(sum(g in p for g in grams) / len(grams), 2) if grams else 0.0


def check_inputs(quote: str, reason: str) -> None:
    if len(_norm(quote)) < MIN_QUOTE_CHARS:
        raise EvidenceError("quote_short", "Quote the exact sentence from the source that breaks the alibi.")
    if len((reason or "").strip()) < MIN_REASON_CHARS:
        raise EvidenceError("reason_short", "Explain in one line why this breaks the alibi.")


def verify_quote(quote: str, evidence: dict, fetch_page=None) -> float:
    """Return the overlap score, or raise if the quote is not in the source."""
    score = quote_overlap(quote, evidence.get("snippet", ""))
    if score >= QUOTE_MATCH:
        return score
    if fetch_page is not None:
        page = fetch_page(evidence["url"]) or ""
        score = max(score, quote_overlap(quote, page))
        if score >= QUOTE_MATCH:
            return score
    raise EvidenceError("quote_not_found", "That sentence does not appear in your evidence. Copy it exactly.")
