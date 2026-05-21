"""In-memory rate limiting for auth endpoints (per-process)."""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm

_lock = threading.Lock()
_hits: dict[str, list[float]] = {}


@dataclass(frozen=True, slots=True)
class LoginRateLimitConfig:
    """Hard-coded limits for ``POST /auth/token``."""

    enabled: bool = True
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


def _check_bucket(*, key: str, limit: int, window_seconds: int) -> int | None:
    """Record one attempt; return Retry-After seconds when limited, else None."""
    now = time.monotonic()
    cutoff = now - window_seconds
    with _lock:
        timestamps = [t for t in _hits.get(key, []) if t >= cutoff]
        if len(timestamps) >= limit:
            oldest = min(timestamps)
            retry_after = max(1, math.ceil(oldest + window_seconds - now))
            return retry_after
        timestamps.append(now)
        _hits[key] = timestamps
    return None


def check_login_rate_limit(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> None:
    """Reject excessive login attempts by client IP and account email."""
    limits = LOGIN_RATE_LIMIT
    if not limits.enabled:
        return

    ip_key = f'login:ip:{_client_ip(request)}'
    retry_after = _check_bucket(
        key=ip_key,
        limit=limits.per_ip,
        window_seconds=limits.window_seconds,
    )
    if retry_after is not None:
        raise _too_many_requests(retry_after)

    email = form_data.username.strip().lower()
    if email:
        email_key = f'login:email:{email}'
        retry_after = _check_bucket(
            key=email_key,
            limit=limits.per_email,
            window_seconds=limits.email_window_seconds,
        )
        if retry_after is not None:
            raise _too_many_requests(retry_after)


def _too_many_requests(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail='Too many login attempts. Please try again later.',
        headers={'Retry-After': str(retry_after)},
    )
