"""Verify OIDC bearer tokens and extract identity claims.

Production flow
---------------
1. Load the issuer OpenID discovery document (cached) to obtain ``jwks_uri``.
2. **PyJWT** verifies the token signature, expiry, and issuer against JWKS.
3. Require ``azp`` (authorized party) against the configured allowlist (session JWTs only).
4. Map configured JWT claim names to :class:`OidcIdentity`.

Test mode (``oidc_config.test_mode``)
-------------------------------------
Accepts pipe-delimited test tokens without crypto verification:

- ``test:<subject>|<display_name>``
- ``test:<subject>|<email>|<display_name>``
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import jwt
from jwt import PyJWK
from jwt.exceptions import InvalidTokenError
from opencloning.http_client import get_http_client

from opencloning_db.config import Config, OidcConfig

TEST_TOKEN_PREFIX = 'test:'

_discovery_cache: dict[str, dict[str, Any]] = {}
_jwks_cache: dict[str, dict[str, Any]] = {}


@dataclass(frozen=True)
class OidcIdentity:
    """Stable external identity extracted from a verified bearer token."""

    provider: str
    subject: str
    display_name: str
    email: str | None = None


def reset_oidc_clients() -> None:
    """Clear cached discovery documents and JWKS payloads (for tests)."""
    _discovery_cache.clear()
    _jwks_cache.clear()


async def verify_oidc_bearer_token(token: str, config: Config) -> OidcIdentity:
    """Validate a bearer token and return the external identity it represents."""
    oidc = config.oidc_config
    if oidc.test_mode:
        return _identity_from_test_token(token, oidc)

    claims = await _decode_verified_claims(token, oidc)
    _check_authorized_party(claims, oidc)
    return _identity_from_verified_claims(claims, oidc)


def _identity_from_test_token(token: str, oidc: OidcConfig) -> OidcIdentity:
    if not token.startswith(TEST_TOKEN_PREFIX):
        raise InvalidTokenError('Invalid test token')
    parts = token[len(TEST_TOKEN_PREFIX) :].split('|')
    if len(parts) == 2:
        subject, display_name = parts
        email = None
    elif len(parts) == 3:
        subject, email, display_name = parts
        email = email.strip() or None
    else:
        raise InvalidTokenError('Invalid test token format')
    subject = subject.strip()
    if not subject:
        raise InvalidTokenError('Invalid test token subject')
    if not display_name:
        raise InvalidTokenError('Invalid test token display_name')
    return OidcIdentity(
        provider=oidc.provider_name,
        subject=subject,
        email=email,
        display_name=display_name,
    )


async def _decode_verified_claims(token: str, oidc: OidcConfig) -> dict[str, Any]:
    """Verify signature and standard claims; return the JWT payload."""
    async with get_http_client() as client:
        discovery = await _fetch_oidc_discovery(oidc.issuer_url, client)
        jwks_uri = discovery.get('jwks_uri')
        issuer = discovery.get('issuer')
        if not jwks_uri:
            raise InvalidTokenError('OIDC discovery document missing jwks_uri')

        signing_key = await _signing_key_for_token(token, jwks_uri, client)
        return jwt.decode(
            token,
            signing_key,
            algorithms=['RS256'],
            issuer=issuer,
            leeway=10,
            options={'require': ['exp', 'sub']},
        )


def _check_authorized_party(claims: dict[str, Any], oidc: OidcConfig) -> None:
    """Require a session token ``azp`` that matches the configured allowlist."""
    azp = claims.get('azp')
    if azp is None or str(azp).rstrip('/') not in oidc.authorized_parties:
        raise InvalidTokenError('Invalid azp claim')


def _identity_from_verified_claims(claims: dict[str, Any], oidc: OidcConfig) -> OidcIdentity:
    subject = claims.get(oidc.subject_claim)
    if subject is None:
        raise InvalidTokenError('Missing subject claim')
    return OidcIdentity(
        provider=oidc.provider_name,
        subject=str(subject),
        email=claims.get(oidc.email_claim),
        display_name=claims.get(oidc.name_claim),
    )


async def _fetch_oidc_discovery(issuer_url: str, client) -> dict[str, Any]:
    cached = _discovery_cache.get(issuer_url)
    if cached is not None:
        return cached
    discovery_url = issuer_url.rstrip('/') + '/.well-known/openid-configuration'
    document = await _fetch_json(client, discovery_url, 'Failed to fetch OIDC discovery document')
    _discovery_cache[issuer_url] = document
    return document


async def _fetch_jwks(jwks_uri: str, client) -> dict[str, Any]:
    cached = _jwks_cache.get(jwks_uri)
    if cached is not None:
        return cached
    document = await _fetch_json(client, jwks_uri, 'Failed to fetch JWKS document')
    _jwks_cache[jwks_uri] = document
    return document


async def _signing_key_for_token(token: str, jwks_uri: str, client) -> Any:
    jwks = await _fetch_jwks(jwks_uri, client)
    keys = jwks.get('keys')
    if not keys:
        raise InvalidTokenError('JWKS document missing keys')

    kid = jwt.get_unverified_header(token).get('kid')
    if kid is None:
        raise InvalidTokenError('Token header missing kid')
    for key_data in keys:
        if key_data.get('kid') == kid:
            return PyJWK.from_dict(key_data).key
    raise InvalidTokenError('Unable to find signing key for token')


async def _fetch_json(client, url: str, error_message: str) -> dict[str, Any]:
    try:
        response = await client.get(url)
        if response.status_code != 200:
            raise InvalidTokenError(error_message)
        payload = response.json()
    except Exception as exc:
        raise InvalidTokenError(error_message) from exc
    if not isinstance(payload, dict):
        raise InvalidTokenError(error_message)
    return payload
