"""Operator sessions: who may change flags, run builds, read cameras, review reports and spend AI quota.

The secret comes from OPERATOR_SECRET or the file named by OPERATOR_SECRET_FILE; it is never sent to the browser,
logged or put in config. Without a secret, operator features are unavailable (503), never open.

A successful login issues a random session id in an HttpOnly, SameSite=Strict cookie (Secure on HTTPS). Sessions
live in this process only (one continuously running backend), expire after SESSION_TTL_S, and logout revokes them.
State-changing requests from a browser must come from an allowed Origin (CSRF guard).
"""
from __future__ import annotations

import hmac
import os
import secrets
import threading
import time
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import Response

COOKIE = "vd_operator"
SESSION_TTL_S = 12 * 3600
MAX_SESSIONS = 64
MAX_LOGIN_FAILS = 10          # per client per window
LOGIN_WINDOW_S = 600

_sessions: dict[str, float] = {}  # session id → expiry (monotonic)
_fails: dict[str, list[float]] = {}
_lock = threading.Lock()


def _secret() -> str | None:
    path = os.environ.get("OPERATOR_SECRET_FILE")
    if path:
        try:
            value = Path(path).read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return value or None
    return os.environ.get("OPERATOR_SECRET") or None


def available() -> bool:
    return _secret() is not None


def allowed_origins() -> set[str]:
    return {o.strip().rstrip("/") for o in os.environ.get("APP_ORIGINS", "").split(",") if o.strip()}


def _same_origin(request: Request) -> str:
    return f"{request.url.scheme}://{request.url.netloc}"


def origin_ok(request: Request) -> bool:
    """A browser request carries Origin; it must be this server or an APP_ORIGINS entry. Non-browser clients
    (no Origin header) cannot carry the SameSite=Strict cookie cross-site, so they are judged by the cookie alone."""
    origin = request.headers.get("origin")
    if origin is None:
        return True
    origin = origin.rstrip("/")
    return origin == _same_origin(request) or origin in allowed_origins()


def _client(request: Request) -> str:
    return request.client.host if request.client else "?"


def login(request: Request, response: Response, secret: str) -> None:
    expected = _secret()
    if expected is None:
        raise HTTPException(503, "Operator password (OPERATOR_SECRET) is not configured")
    now = time.monotonic()
    who = _client(request)
    with _lock:
        recent = [t for t in _fails.get(who, []) if now - t < LOGIN_WINDOW_S]
        if len(recent) >= MAX_LOGIN_FAILS:
            raise HTTPException(429, "Too many failed sign-in attempts; retry later")
        if not hmac.compare_digest(secret.encode(), expected.encode()):
            recent.append(now)
            _fails[who] = recent
            if len(_fails) > 1024:  # bounded: drop the oldest clients
                for k in list(_fails)[:256]:
                    _fails.pop(k, None)
            raise HTTPException(401, "Incorrect operator password")
        _fails.pop(who, None)
        for sid in [s for s, exp in _sessions.items() if exp <= now]:
            del _sessions[sid]
        while len(_sessions) >= MAX_SESSIONS:
            del _sessions[min(_sessions, key=_sessions.get)]
        sid = secrets.token_urlsafe(32)
        _sessions[sid] = now + SESSION_TTL_S
    response.set_cookie(COOKIE, sid, max_age=SESSION_TTL_S, httponly=True, samesite="strict",
                        secure=request.url.scheme == "https", path="/")


def logout(request: Request, response: Response) -> None:
    sid = request.cookies.get(COOKIE)
    with _lock:
        if sid:
            _sessions.pop(sid, None)
    response.delete_cookie(COOKIE, path="/")


def is_operator(request: Request) -> bool:
    if not available():
        return False
    sid = request.cookies.get(COOKIE)
    if not sid:
        return False
    with _lock:
        exp = _sessions.get(sid)
        if exp is None:
            return False
        if exp <= time.monotonic():
            del _sessions[sid]
            return False
    return True


def require_operator(request: Request) -> str:
    """FastAPI dependency: the reviewer label for an operator request, else 503/401."""
    if not available():
        raise HTTPException(503, "Operator features are disabled on this server")
    if not is_operator(request):
        raise HTTPException(401, "Operator sign-in required")
    return "operator"
