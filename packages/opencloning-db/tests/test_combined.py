from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

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
