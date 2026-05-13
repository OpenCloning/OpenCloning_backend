from fastapi.testclient import TestClient

from opencloning_db.combined import app


client = TestClient(app)


def test_combined_root_lists_mounted_apps():
    response = client.get('/')

    assert response.status_code == 200
    assert response.json() == {
        'cloning': '/cloning',
        'cloning_docs': '/cloning/docs',
        'db': '/db',
        'db_docs': '/db/docs',
    }


def test_combined_openapi_exposes_cloning_and_db_apps():
    cloning_response = client.get('/cloning/openapi.json')
    db_response = client.get('/db/openapi.json')

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
