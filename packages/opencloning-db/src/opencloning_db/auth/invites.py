"""Registration allowlist helpers backed by database rows."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from opencloning_db.config import Config
from opencloning_db.models import EmailWhitelist

REGISTRATION_UNAVAILABLE_DETAIL = 'Registration is not available for this email.'


def normalize_email(email: str) -> str:
    return email.strip().lower()


def registration_invites_enabled(config: Config) -> bool:
    return config.registration_whitelist_enabled


def require_invited_email(email: str, session: Session, config: Config) -> None:
    """When whitelist enforcement is enabled, email must appear in the whitelist table."""
    if not registration_invites_enabled(config):
        return
    normalized = normalize_email(email)
    if session.scalar(select(EmailWhitelist.id).where(EmailWhitelist.email == normalized)) is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=REGISTRATION_UNAVAILABLE_DETAIL,
        )
