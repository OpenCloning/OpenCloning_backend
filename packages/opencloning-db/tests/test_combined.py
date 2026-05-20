from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException

from opencloning_db.api import app as db_app
from opencloning_db.combined import create_app


@pytest.fixture
def combined_client(engine_client_config) -> Generator[TestClient, None, None]:
    with TestClient(create_app(db_app=db_app)) as client:
        yield client


def test_combined_root_lists_mounted_apps(combined_client: TestClient):
    response = combined_client.get('/')

    assert response.status_code == 200
    assert response.json() == {
        'cloning': '/cloning',
        'cloning_docs': '/cloning/docs',
        'db': '/db',
        'db_docs': '/db/docs',
    }


def test_combined_cloning_openapi_requires_auth(combined_client: TestClient):
    unauthenticated_response = combined_client.get('/cloning/openapi.json')

    assert unauthenticated_response.status_code == 401
    assert unauthenticated_response.json() == {'detail': 'Could not validate credentials'}
    assert unauthenticated_response.headers.get('www-authenticate') == 'Bearer'


def test_options_request_is_not_authenticated(combined_client: TestClient):
    response = combined_client.options(
        '/cloning/version',
        headers={
            'Origin': 'http://localhost:3000',
            'Access-Control-Request-Method': 'GET',
        },
    )
    assert response.status_code == 200


def test_wrong_auth_header_is_rejected(combined_client: TestClient):
    response = combined_client.get('/cloning/openapi.json', headers={'Authorization': 'Bearer wrong-token'})

    assert response.status_code == 401
    assert response.json() == {'detail': 'Could not validate credentials'}
    assert response.headers.get('www-authenticate') == 'Bearer'


def test_invalid_auth_header_is_rejected(combined_client: TestClient):
    response = combined_client.get('/cloning/openapi.json', headers={'Authorization': 'Basic invalid-token'})

    assert response.status_code == 401
    assert response.json() == {'detail': 'Could not validate credentials'}
    assert response.headers.get('www-authenticate') == 'Bearer'


def test_combined_app_uses_injected_cloning_verifier(engine_client_config):
    def allow_all(_headers) -> None:
        return None

    with TestClient(create_app(db_app=db_app, cloning_verifier=allow_all)) as client:
        response = client.get('/cloning/openapi.json')

    assert response.status_code == 200

    def reject_all(_headers) -> None:
        raise HTTPException(status_code=401, detail='Could not validate credentials')

    with TestClient(create_app(db_app=db_app, cloning_verifier=reject_all)) as client:
        response = client.get('/cloning/openapi.json')

    assert response.status_code == 401
    assert response.json() == {'detail': 'Could not validate credentials'}


def test_combined_openapi_exposes_cloning_and_db_apps_for_authenticated_user(combined_client: TestClient):
    register_response = combined_client.post(
        '/db/auth/register',
        json={
            'email': 'combined-user@example.com',
            'password': 'secret-password',
            'display_name': 'Combined User',
        },
    )
    assert register_response.status_code == 200
    token = register_response.json()['access_token']

    cloning_response = combined_client.get(
        '/cloning/openapi.json',
        headers={'Authorization': f'Bearer {token}'},
    )
    db_response = combined_client.get('/db/openapi.json')

    assert cloning_response.status_code == 200
    assert db_response.status_code == 200

    cloning_paths = cloning_response.json()['paths']
    db_schema = db_response.json()
    db_paths = db_schema['paths']
    password_flow = db_schema['components']['securitySchemes']['OAuth2PasswordBearer']['flows']['password']

    assert '/' in cloning_paths
    assert '/auth/register' in db_paths
    assert '/workspaces' in db_paths
    assert password_flow['tokenUrl'] == 'auth/token'
