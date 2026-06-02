"""Signup allowlist from object-storage text file."""

import opencloning_db.config as app_config
import pytest
from sqlalchemy.orm import Session

import opencloning_db.db as db_module

from opencloning_db.auth.invites import (
    REGISTRATION_UNAVAILABLE_DETAIL,
    registration_invites_enabled,
    require_invited_email,
    normalize_email,
)
from opencloning_db.models import EmailWhitelist

readonly_db = pytest.mark.readonly_db


def _add_invited_emails(config, *emails: str) -> None:
    with Session(db_module.get_engine(config)) as session:
        session.add_all(EmailWhitelist(email=normalize_email(email)) for email in emails)
        session.commit()


@pytest.fixture
def auth_client(request):
    fixture_name = (
        'engine_client_config_readonly'
        if request.node.get_closest_marker('readonly_db')
        else 'engine_client_config_write'
    )
    _, client, _ = request.getfixturevalue(fixture_name)
    return client


def test_registration_invites_disabled_when_path_empty(postgres_test_config_write):
    assert not registration_invites_enabled(postgres_test_config_write)
    with Session(db_module.get_engine(postgres_test_config_write)) as session:
        require_invited_email('anyone@example.com', session, postgres_test_config_write)


def test_register_open_when_invite_path_empty(auth_client):
    email = 'open@example.com'
    response = auth_client.post(
        '/auth/register',
        json={'email': email, 'password': 'secret-password', 'display_name': 'Open'},
    )
    assert response.status_code == 200


def test_register_rejected_when_not_in_invite_file(auth_client, postgres_test_config_write):
    previous = app_config.config
    cfg = postgres_test_config_write.model_copy(update={'registration_whitelist_enabled': True})
    app_config.set_config(cfg)
    _add_invited_emails(cfg, 'other@example.com')
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


def test_register_succeeds_when_email_in_invite_file(auth_client, postgres_test_config_write):
    previous = app_config.config
    cfg = postgres_test_config_write.model_copy(update={'registration_whitelist_enabled': True})
    app_config.set_config(cfg)
    email = 'invited@example.com'
    _add_invited_emails(cfg, email.upper())
    try:
        response = auth_client.post(
            '/auth/register',
            json={'email': email, 'password': 'secret-password', 'display_name': 'Invited'},
        )
        assert response.status_code == 200
    finally:
        app_config.set_config(previous)
