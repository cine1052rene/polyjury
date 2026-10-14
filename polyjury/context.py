"""Per-request credentials, carried to every thread the request starts.

A signed-in visitor may bring their own Nebius key (BYOK) and has a GitHub token. Neither is
stored on the server: both arrive in an encrypted cookie with each request, live in these
context variables for that request only, and are gone when it ends.

concurrent.futures does not copy context variables into worker threads, so the pools used
across the pipeline are this subclass, which does."""
from __future__ import annotations

import contextvars
import os
from concurrent.futures import ThreadPoolExecutor

NEBIUS_KEY: contextvars.ContextVar[str | None] = contextvars.ContextVar("nebius_key", default=None)
GITHUB_TOKEN: contextvars.ContextVar[str | None] = contextvars.ContextVar("github_token", default=None)


class Pool(ThreadPoolExecutor):
    """ThreadPoolExecutor whose tasks see the submitting request's credentials."""

    def submit(self, fn, /, *args, **kwargs):  # noqa: D401
        ctx = contextvars.copy_context()
        return super().submit(ctx.run, fn, *args, **kwargs)


def set_request(nebius_key: str | None, github_token: str | None) -> None:
    """Called at the start of every API request. Always sets both, so a value can never leak
    from one request into the next one that reuses the same worker thread."""
    NEBIUS_KEY.set(nebius_key or None)
    GITHUB_TOKEN.set(github_token or None)


def github_token() -> str:
    """The visitor's own token first (their rate limit, not the site's), then the server's."""
    return GITHUB_TOKEN.get() or os.environ.get("GITHUB_TOKEN", "")
