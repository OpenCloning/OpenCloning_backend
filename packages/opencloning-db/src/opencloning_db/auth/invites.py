"""Registration allowlist loaded from a text file in object storage."""

from __future__ import annotations

from fastapi import HTTPException, status

from opencloning_db.config import Config
from opencloning_db.storage import get_storage

REGISTRATION_UNAVAILABLE_DETAIL = 'Registration is not available for this email.'


def normalize_email(email: str) -> str:
    return email.strip().lower()


def registration_invites_enabled(config: Config) -> bool:
    return bool(config.registration_invites_object_key.strip())


def _parse_invite_file(content: str) -> set[str]:
    return set(normalize_email(line) for line in content.splitlines())


def load_invited_emails(config: Config) -> set[str]:
    key = config.registration_invites_object_key.strip()
    content = get_storage().read_text(key)
    return _parse_invite_file(content)


def require_invited_email(email: str, config: Config) -> None:
    """When an invite file path is configured, email must appear on a line in that object."""
    if not registration_invites_enabled(config):
        return
    normalized = normalize_email(email)
    if normalized not in load_invited_emails(config):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=REGISTRATION_UNAVAILABLE_DETAIL,
        )
