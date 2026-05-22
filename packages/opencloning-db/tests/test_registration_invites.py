"""Signup allowlist from object-storage text file."""

import opencloning_db.config as app_config
import pytest

from opencloning_db.auth.invites import (
    REGISTRATION_UNAVAILABLE_DETAIL,
    registration_invites_enabled,
    require_invited_email,
)
from opencloning_db.storage import ObjectStorage


def _write_invite_file(config, *emails: str) -> None:
    ObjectStorage(config).write_text(
        config.registration_invites_object_key,
        '\n'.join(emails) + '\n',
    )


@pytest.fixture
def auth_client(engine_client_config):
    _, client, _ = engine_client_config
    return client


def test_registration_invites_disabled_when_path_empty(postgres_test_config):
    assert not registration_invites_enabled(postgres_test_config)
    require_invited_email('anyone@example.com', postgres_test_config)


def test_register_open_when_invite_path_empty(auth_client):
    email = 'open@example.com'
    response = auth_client.post(
        '/auth/register',
        json={'email': email, 'password': 'secret-password', 'display_name': 'Open'},
    )
    assert response.status_code == 200


def test_register_rejected_when_not_in_invite_file(auth_client, postgres_test_config):
    key = 'registration-invites.txt'
    previous = app_config.config
    cfg = postgres_test_config.model_copy(update={'registration_invites_object_key': key})
    app_config.set_config(cfg)
    _write_invite_file(cfg, 'other@example.com')
    try:
        email = 'uninvited@example.com'
        response = auth_client.post(
            '/auth/register',
            json={'email': email, 'password': 'secret-password', 'display_name': 'User'},
        )
        assert response.status_code == 403
        assert response.json()['detail'] == REGISTRATION_UNAVAILABLE_DETAIL
    finally:
        app_config.set_config(previous)


def test_register_succeeds_when_email_in_invite_file(auth_client, postgres_test_config):
    key = 'registration-invites.txt'
    previous = app_config.config
    cfg = postgres_test_config.model_copy(update={'registration_invites_object_key': key})
    app_config.set_config(cfg)
    email = 'invited@example.com'
    _write_invite_file(cfg, email.upper())
    try:
        response = auth_client.post(
            '/auth/register',
            json={'email': email, 'password': 'secret-password', 'display_name': 'Invited'},
        )
        assert response.status_code == 200
    finally:
        app_config.set_config(previous)
