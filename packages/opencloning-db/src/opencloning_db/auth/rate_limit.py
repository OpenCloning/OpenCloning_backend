"""In-memory rate limiting for auth endpoints (per-process)."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
import os
from opencloning_db.config import parse_bool

_lock = threading.Lock()
_hits: dict[str, list[float]] = {}


@dataclass(frozen=True, slots=True)
class LoginRateLimitConfig:
    """Hard-coded limits for ``POST /auth/token``."""

    enabled: bool = parse_bool(os.environ.get('OPENCLONING_RATE_LIMIT_ENABLED', True))
    per_ip: int = 20
    window_seconds: int = 60
    per_email: int = 10
    email_window_seconds: int = 300


LOGIN_RATE_LIMIT = LoginRateLimitConfig()


def reset_login_rate_limiter() -> None:
    """Clear tracked login attempts (for tests)."""
    with _lock:
        _hits.clear()


def _client_ip(request: Request) -> str:
    if request.client is None:
        return 'unknown'
    return request.client.host


def _is_limited(*, key: str, limit: int, window_seconds: int) -> bool:
    now = time.monotonic()
    cutoff = now - window_seconds
    with _lock:
        timestamps = [t for t in _hits.get(key, []) if t >= cutoff]
        if len(timestamps) >= limit:
            return True
        timestamps.append(now)
        _hits[key] = timestamps
    return False


def check_login_rate_limit(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> None:
    """Reject excessive login attempts by client IP and account email."""
    limits = LOGIN_RATE_LIMIT
    if not limits.enabled:
        return

    if _is_limited(
        key=f'login:ip:{_client_ip(request)}',
        limit=limits.per_ip,
        window_seconds=limits.window_seconds,
    ):
        raise _too_many_requests()

    email = form_data.username.strip().lower()
    if email and _is_limited(
        key=f'login:email:{email}',
        limit=limits.per_email,
        window_seconds=limits.email_window_seconds,
    ):
        raise _too_many_requests()


def _too_many_requests() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail='Too many login attempts. Please try again later.',
    )
