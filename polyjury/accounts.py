"""Optional sign-in with GitHub, and bring-your-own Nebius key — with nothing stored server-side.

Anonymous use stays exactly as it was. Signing in adds three things: your own rate limit
(not your network's), your public repositories to pick from, and GitHub API calls made under
your token instead of the site's shared one. BYOK makes the model calls of your runs bill to
your own Nebius Token Factory key.

There is no database. The GitHub token and the Nebius key are encrypted with the server's
secret and handed back to the browser as httpOnly cookies; each request brings them, they are
decrypted in memory for that request (polyjury.context) and never written or logged. The OAuth
app asks for no scopes, so the token can only read what is public anyway. Signing out revokes
the token at GitHub. Policy page: /privacy.html."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from polyjury import context

SESSION, BYOK, STATE = "pj_session", "pj_byok", "pj_state"
SESSION_DAYS = 7
router = APIRouter()


def _fernet() -> Fernet:
    secret = os.environ.get("POLYJURY_SECRET") or os.environ.get("NEBIUS_API_KEY", "dev")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"polyjury-cookie:" + secret.encode()).digest()))


def _seal(data: dict) -> str:
    return _fernet().encrypt(json.dumps(data).encode()).decode()


def _open(value: str | None) -> dict:
    if not value:
        return {}
    try:
        data = json.loads(_fernet().decrypt(value.encode(), ttl=SESSION_DAYS * 86400))
    except (InvalidToken, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def enabled() -> bool:
    return bool(os.environ.get("GITHUB_CLIENT_ID") and os.environ.get("GITHUB_CLIENT_SECRET"))


def _https(request: Request) -> bool:
    return request.headers.get("x-forwarded-proto", request.url.scheme) == "https"


def _cookie(resp, request: Request, name: str, value: str, max_age: int) -> None:
    resp.set_cookie(name, value, max_age=max_age, httponly=True, secure=_https(request),
                    samesite="lax", path="/")


def user(request: Request) -> dict:
    return _open(request.cookies.get(SESSION))


def bind(request: Request) -> tuple[str | None, bool]:
    """Start of every API request: put this visitor's credentials (or none) in the request
    context. Returns (GitHub user id or None, whether they brought their own key)."""
    u = user(request)
    key = _open(request.cookies.get(BYOK)).get("k")
    context.set_request(key, u.get("t"))
    return (str(u["id"]) if u.get("id") else None), bool(key)


def _gh(url: str, token: str | None = None, data: bytes | None = None, method: str | None = None,
        headers: dict | None = None) -> dict:
    h = {"Accept": "application/vnd.github+json", "User-Agent": "polyjury", **(headers or {})}
    if token:
        h["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    raw = urllib.request.urlopen(req, timeout=20).read()
    return json.loads(raw) if raw else {}


def _callback_url(request: Request) -> str:
    if os.environ.get("GITHUB_REDIRECT_URI"):
        return os.environ["GITHUB_REDIRECT_URI"]
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    return f"{'https' if _https(request) else 'http'}://{host}/api/auth/callback"


@router.get("/api/auth/login")
def login(request: Request):
    if not enabled():
        raise HTTPException(404, "Sign-in is not set up on this deployment.")
    state = secrets.token_urlsafe(24)
    q = urllib.parse.urlencode({"client_id": os.environ["GITHUB_CLIENT_ID"], "redirect_uri": _callback_url(request),
                                "scope": "", "state": state, "allow_signup": "true"})
    resp = RedirectResponse(f"https://github.com/login/oauth/authorize?{q}", status_code=302)
    _cookie(resp, request, STATE, state, 600)
    return resp


@router.get("/api/auth/callback")
def callback(request: Request, code: str = "", state: str = ""):
    if not enabled():
        raise HTTPException(404, "Sign-in is not set up on this deployment.")
    expected = request.cookies.get(STATE, "")
    if not code or not expected or not secrets.compare_digest(state, expected):
        return RedirectResponse("/?signin=failed", status_code=302)
    try:
        body = urllib.parse.urlencode({"client_id": os.environ["GITHUB_CLIENT_ID"],
                                       "client_secret": os.environ["GITHUB_CLIENT_SECRET"],
                                       "code": code, "redirect_uri": _callback_url(request)}).encode()
        tok = _gh("https://github.com/login/oauth/access_token", data=body,
                  headers={"Accept": "application/json"}).get("access_token")
        me = _gh("https://api.github.com/user", token=tok) if tok else {}
    except Exception:  # noqa: BLE001
        tok, me = None, {}
    if not tok or not me.get("id"):
        return RedirectResponse("/?signin=failed", status_code=302)
    resp = RedirectResponse("/", status_code=302)
    _cookie(resp, request, SESSION, _seal({"t": tok, "id": me["id"], "login": me.get("login", ""),
                                           "avatar": me.get("avatar_url", ""), "at": int(time.time())}),
            SESSION_DAYS * 86400)
    resp.delete_cookie(STATE, path="/")
    return resp


@router.post("/api/auth/logout")
def logout(request: Request):
    """Forget the cookies and revoke the token at GitHub, so it is dead even if a copy survived."""
    tok = user(request).get("t")
    if tok and enabled():
        basic = base64.b64encode(f"{os.environ['GITHUB_CLIENT_ID']}:{os.environ['GITHUB_CLIENT_SECRET']}".encode()).decode()
        try:
            _gh(f"https://api.github.com/applications/{os.environ['GITHUB_CLIENT_ID']}/token",
                data=json.dumps({"access_token": tok}).encode(), method="DELETE",
                headers={"Authorization": f"Basic {basic}"})
        except Exception:  # noqa: BLE001 - the cookie is cleared either way
            pass
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION, path="/")
    resp.delete_cookie(BYOK, path="/")
    return resp


@router.get("/api/me")
def me(request: Request) -> dict:
    u = user(request)
    return {"auth": enabled(), "byok": bool(_open(request.cookies.get(BYOK)).get("k")),
            "user": {"login": u.get("login", ""), "avatar": u.get("avatar", "")} if u.get("id") else None}


@router.get("/api/me/repos")
def my_repos(request: Request):
    """Your public repositories, most recently pushed first — to pick from instead of pasting."""
    u = user(request)
    if not u.get("t"):
        raise HTTPException(401, "Sign in with GitHub first.")
    try:
        repos = _gh(f"https://api.github.com/users/{urllib.parse.quote(u['login'])}/repos"
                    "?type=owner&sort=pushed&per_page=50", token=u["t"])
    except urllib.error.HTTPError as exc:
        if exc.code == 401:  # revoked at GitHub: this session is over
            resp = JSONResponse({"detail": "Your GitHub sign-in has expired. Sign in again."}, status_code=401)
            resp.delete_cookie(SESSION, path="/")
            return resp
        raise HTTPException(502, "GitHub did not answer; try again.") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, "GitHub did not answer; try again.") from exc
    return {"repos": [{"name": r.get("full_name", ""), "url": r.get("html_url", ""), "pushed": r.get("pushed_at", "")}
                      for r in repos if isinstance(r, dict) and not r.get("private") and not r.get("archived")]}


class KeyIn(BaseModel):
    key: str


@router.post("/api/byok")
def set_key(body: KeyIn, request: Request):
    """Check the key against Nebius once, then hand it back encrypted. It is never echoed."""
    key = body.key.strip()
    if not re.fullmatch(r"[A-Za-z0-9._\-]{20,600}", key):
        raise HTTPException(400, "That does not look like a Nebius Token Factory API key.")
    from core.nebius_client import NebiusClient  # imported here: the module needs config at import
    try:
        ok = any("nemotron" in m.lower() for m in NebiusClient(api_key=key).list_models())
    except Exception:  # noqa: BLE001
        ok = False
    if not ok:
        raise HTTPException(400, "Nebius Token Factory refused that key, or it cannot reach Nemotron.")
    resp = JSONResponse({"ok": True})
    _cookie(resp, request, BYOK, _seal({"k": key}), SESSION_DAYS * 86400)
    return resp


@router.delete("/api/byok")
def clear_key(request: Request):
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(BYOK, path="/")
    return resp
