"""Auth register / token / me flow."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest

import opencloning_db.auth.rate_limit as login_rate_limit
from opencloning_db.auth.rate_limit import LoginRateLimitConfig, reset_login_rate_limiter
from opencloning_db.config import get_config


@pytest.fixture
def auth_client(engine_client_config):
    _, client, _ = engine_client_config
    return client


def test_register_token_me(auth_client):
    """Register; /auth/me and password login match user and issue JWT."""
    email = f"user-{uuid4().hex}@example.com"
    r = auth_client.post(
        '/auth/register',
        json={
            'email': email,
            'password': 'secret-password',
            'display_name': 'Test User',
        },
    )
    assert r.status_code == 200
    register_body = r.json()
    assert set(register_body) == {'access_token', 'token_type'}
    token = register_body['access_token']
    assert register_body['token_type'] == 'bearer'

    r2 = auth_client.get(
        '/auth/me',
        headers={'Authorization': f"Bearer {token}"},
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body['email'] == email
    assert body['display_name'] == 'Test User'
    assert body['is_instance_admin'] is False

    r3 = auth_client.post(
        '/auth/token',
        data={'username': email, 'password': 'secret-password'},
    )
    assert r3.status_code == 200
    token_body = r3.json()
    assert set(token_body) == {'access_token', 'token_type'}
    assert token_body['token_type'] == 'bearer'
    assert token_body['access_token']


def test_login_invalid(auth_client):
    """Wrong credentials return 401 (opaque error message)."""
    r = auth_client.post(
        '/auth/token',
        data={'username': 'nobody@example.com', 'password': 'wrong'},
    )
    assert r.status_code == 401
    assert 'Incorrect' in r.json()['detail']


def test_login_wrong_password_for_existing_user_401(auth_client):
    """Existing user + wrong password follows verify_password false branch."""
    email = f"user-{uuid4().hex}@example.com"
    r1 = auth_client.post(
        '/auth/register',
        json={'email': email, 'password': 'correct-password', 'display_name': 'User'},
    )
    assert r1.status_code == 200

    r2 = auth_client.post(
        '/auth/token',
        data={'username': email, 'password': 'wrong-password'},
    )
    assert r2.status_code == 401
    assert r2.json()['detail'] == 'Incorrect username or password'
    assert r2.headers.get('www-authenticate') == 'Bearer'


def test_register_duplicate_email_returns_400(auth_client):
    """Second registration with the same email is rejected with 400."""
    email = f"dup-{uuid4().hex}@example.com"
    r1 = auth_client.post(
        '/auth/register',
        json={'email': email, 'password': 'password1a', 'display_name': 'User A'},
    )
    assert r1.status_code == 200
    r2 = auth_client.post(
        '/auth/register',
        json={'email': email, 'password': 'password2b', 'display_name': 'User B'},
    )
    assert r2.status_code == 400
    assert r2.json()['detail'] == 'Email already registered'


def test_register_invalid_email_422(auth_client):
    """Pydantic rejects a non-email string in the email field."""
    r = auth_client.post(
        '/auth/register',
        json={
            'email': 'not-an-email',
            'password': 'secret-pass',
            'display_name': 'User',
        },
    )
    assert r.status_code == 422
    detail = r.json()['detail']
    assert isinstance(detail, list)
    assert detail


def test_register_short_display_name_422(auth_client):
    """display_name must satisfy RegisterBody min_length=4."""
    r = auth_client.post(
        '/auth/register',
        json={
            'email': f"u-{uuid4().hex}@example.com",
            'password': 'secret-pass',
            'display_name': 'abc',
        },
    )
    assert r.status_code == 422
    detail = r.json()['detail']
    assert isinstance(detail, list)
    assert detail


def test_register_short_password_422(auth_client):
    """Password must satisfy RegisterBody min_length=8."""
    r = auth_client.post(
        '/auth/register',
        json={
            'email': f"u-{uuid4().hex}@example.com",
            'password': 'short',
            'display_name': 'User',
        },
    )
    assert r.status_code == 422
    detail = r.json()['detail']
    assert isinstance(detail, list)
    assert detail


def test_register_empty_password_422(auth_client):
    """Password must satisfy RegisterBody min_length=8."""
    r = auth_client.post(
        '/auth/register',
        json={
            'email': f"u-{uuid4().hex}@example.com",
            'password': '',
            'display_name': 'User',
        },
    )
    assert r.status_code == 422
    detail = r.json()['detail']
    assert isinstance(detail, list)
    assert detail


def test_login_sql_injection_like_username_still_401(auth_client):
    """SQL-like usernames do not bypass login; ORM still returns 401."""
    r = auth_client.post(
        '/auth/token',
        data={'username': "x' OR '1'='1", 'password': 'y'},
    )
    assert r.status_code == 401
    assert 'Incorrect' in r.json()['detail']


def test_me_malformed_authorization_401(auth_client):
    """/auth/me rejects tokens that are not valid JWTs."""
    r = auth_client.get(
        '/auth/me',
        headers={'Authorization': 'Bearer not-a-valid-jwt'},
    )
    assert r.status_code == 401
    assert r.json()['detail'] == 'Could not validate credentials'
    assert r.json()['detail'] == 'Could not validate credentials'


def test_me_wrong_secret_jwt_401(auth_client):
    """JWT signed with a different key than the app config is rejected."""
    bad = jwt.encode(
        {'sub': '1', 'exp': datetime.now(timezone.utc) + timedelta(hours=1)},
        'wrong-secret-key-at-least-32bytes-long!!',
        algorithm='HS256',
    )
    r = auth_client.get(
        '/auth/me',
        headers={'Authorization': f"Bearer {bad}"},
    )
    assert r.status_code == 401


def test_me_expired_jwt_401(auth_client):
    """Expired JWTs are rejected when decoding current user."""
    config = get_config()
    expired = jwt.encode(
        {'sub': '1', 'exp': datetime.now(timezone.utc) - timedelta(seconds=1)},
        config.jwt_secret,
        algorithm=config.jwt_algorithm,
    )
    r = auth_client.get(
        '/auth/me',
        headers={'Authorization': f"Bearer {expired}"},
    )
    assert r.status_code == 401
    assert r.json()['detail'] == 'Could not validate credentials'


def test_me_token_without_sub_claim_401(auth_client):
    """JWT missing subject claim is rejected."""
    config = get_config()
    bad = jwt.encode(
        {'exp': datetime.now(timezone.utc) + timedelta(hours=1)},
        config.jwt_secret,
        algorithm=config.jwt_algorithm,
    )
    r = auth_client.get(
        '/auth/me',
        headers={'Authorization': f"Bearer {bad}"},
    )
    assert r.status_code == 401
    assert r.json()['detail'] == 'Could not validate credentials'


def test_me_token_with_nonexistent_user_sub_401(auth_client):
    """JWT with valid sub for unknown user id is rejected."""
    config = get_config()
    bad = jwt.encode(
        {'sub': '99999999', 'exp': datetime.now(timezone.utc) + timedelta(hours=1)},
        config.jwt_secret,
        algorithm=config.jwt_algorithm,
    )
    r = auth_client.get(
        '/auth/me',
        headers={'Authorization': f"Bearer {bad}"},
    )
    assert r.status_code == 401
    assert r.json()['detail'] == 'Could not validate credentials'


def test_login_rate_limited_by_ip(auth_client, monkeypatch):
    """Repeated login attempts from one client are rejected with 429."""
    reset_login_rate_limiter()
    monkeypatch.setattr(
        login_rate_limit,
        'LOGIN_RATE_LIMIT',
        LoginRateLimitConfig(
            enabled=True,
            per_ip=2,
            window_seconds=60,
            per_email=100,
            email_window_seconds=300,
        ),
    )
    for attempt in range(3):
        response = auth_client.post(
            '/auth/token',
            data={'username': f'nobody-{attempt}@example.com', 'password': 'wrong'},
        )
    assert response.status_code == 429
    assert response.json()['detail'] == 'Too many login attempts. Please try again later.'


def test_login_rate_limited_by_email(auth_client, monkeypatch):
    """Repeated login attempts from one email are rejected with 429."""
    reset_login_rate_limiter()
    monkeypatch.setattr(
        login_rate_limit,
        'LOGIN_RATE_LIMIT',
        LoginRateLimitConfig(
            enabled=True,
            per_ip=100,
            window_seconds=60,
            per_email=2,
            email_window_seconds=60,
        ),
    )
    for _attempt in range(3):
        response = auth_client.post(
            '/auth/token',
            data={'username': 'nobody@example.com', 'password': 'wrong'},
        )
    assert response.status_code == 429
    assert response.json()['detail'] == 'Too many login attempts. Please try again later.'
