"""Workspace listing endpoint tests."""

import pytest
from sqlalchemy.orm import Session

from .helpers import (
    attach_standard_tokens,
    bearer_headers,
    fetch_token,
    seed_standard_users,
)


@pytest.fixture
def workspaces_client(request):
    if request.node.get_closest_marker('readonly_db'):
        return request.getfixturevalue('_workspaces_client_readonly')
    engine, client, _ = request.getfixturevalue('engine_client_config_write')
    return _seed_workspaces_context(engine, client)


@pytest.fixture(scope='module')
def _workspaces_client_readonly(engine_client_config_readonly):
    engine, client, _ = engine_client_config_readonly
    return _seed_workspaces_context(engine, client)


readonly_db = pytest.mark.readonly_db


def _seed_workspaces_context(engine, client):
    with Session(engine) as session:
        ctx = seed_standard_users(session)
        session.commit()

    attach_standard_tokens(ctx, client)
    ctx['token_owner_w1_viewer_w2'] = fetch_token(
        client,
        ctx['owner_w1_viewer_w2_email'],
        ctx['owner_w1_viewer_w2_pw'],
    )
    ctx['token'] = ctx['token_owner_w1_viewer_w2']
    return ctx


@readonly_db
def test_get_workspaces_lists_only_user_accessible(workspaces_client):
    """List workspaces returns only this user's memberships and roles."""
    c = workspaces_client['client']
    tok = workspaces_client['token']
    response = c.get('/workspaces', headers=bearer_headers(tok))
    assert response.status_code == 200

    data = response.json()
    assert len(data) == 2
    assert data[0]['name'] == 'Workspace One'
    assert data[0]['role'] == 'owner'
    assert data[1]['name'] == 'Workspace Two'
    assert data[1]['role'] == 'viewer'


@readonly_db
def test_get_workspace_by_id_member_ok(workspaces_client):
    """Member can GET workspace by id from fixture (not hardcoded)."""
    c = workspaces_client['client']
    tok = workspaces_client['token']
    wid = workspaces_client['w1']
    response = c.get(
        f"/workspaces/{wid}",
        headers=bearer_headers(tok),
    )
    assert response.status_code == 200
    body = response.json()
    assert body['id'] == wid
    assert body['name'] == 'Workspace One'
    assert body['role'] == 'owner'


@readonly_db
def test_get_workspace_by_id_not_found(workspaces_client):
    """GET unknown workspace id returns 404."""
    c = workspaces_client['client']
    tok = workspaces_client['token']
    response = c.get(
        '/workspaces/999999',
        headers=bearer_headers(tok),
    )
    assert response.status_code == 404
    assert response.json()['detail'] == 'Workspace not found'


@readonly_db
def test_get_workspace_by_id_forbidden_non_member(workspaces_client):
    """User with no access to a workspace gets 403 when fetching it by id."""
    c = workspaces_client['client']
    tok = workspaces_client['token']
    response = c.get(
        f"/workspaces/{workspaces_client['w3']}",
        headers=bearer_headers(tok),
    )
    assert response.status_code == 403
    assert 'Not allowed' in response.json()['detail']


@readonly_db
def test_create_workspace_forbidden_non_admin(workspaces_client):
    """Non-instance-admin users cannot POST /workspaces."""
    c = workspaces_client['client']
    tok = workspaces_client['token']
    response = c.post(
        '/workspaces',
        headers=bearer_headers(tok),
        json={'name': 'Should Not Work'},
    )
    assert response.status_code == 403
    assert response.json()['detail'] == 'Only instance admins can create workspaces'


def test_create_workspace_creates_owner_membership(workspaces_client):
    """Instance admin POST /workspaces creates workspace and becomes owner."""
    c = workspaces_client['client']
    tok = workspaces_client['token_instance_admin']
    response = c.post(
        '/workspaces',
        headers=bearer_headers(tok),
        json={'name': 'My Created Workspace'},
    )
    assert response.status_code == 200
    body = response.json()
    assert body['id'] > 0
    assert body['name'] == 'My Created Workspace'
    assert body['role'] == 'owner'

    list_response = c.get(
        '/workspaces',
        headers=bearer_headers(tok),
    )
    assert list_response.status_code == 200
    names = {workspace['name'] for workspace in list_response.json()}
    assert names == {'My Created Workspace'}


def test_patch_workspace_owner_can_rename(workspaces_client):
    """Workspace owner can PATCH the workspace name."""
    c = workspaces_client['client']
    tok = workspaces_client['token']
    response = c.patch(
        f"/workspaces/{workspaces_client['w1']}",
        headers=bearer_headers(tok),
        json={'name': 'Workspace One Renamed'},
    )
    assert response.status_code == 200
    body = response.json()
    assert body['id'] == workspaces_client['w1']
    assert body['name'] == 'Workspace One Renamed'
    assert body['role'] == 'owner'

    get_response = c.get(
        f"/workspaces/{workspaces_client['w1']}",
        headers=bearer_headers(tok),
    )
    assert get_response.status_code == 200
    assert get_response.json()['name'] == 'Workspace One Renamed'


@readonly_db
def test_patch_workspace_forbidden_for_viewer(workspaces_client):
    """Workspace viewer cannot rename the workspace."""
    c = workspaces_client['client']
    tok = workspaces_client['token_viewer_w1']
    response = c.patch(
        f"/workspaces/{workspaces_client['w1']}",
        headers=bearer_headers(tok),
        json={'name': 'Should Not Work'},
    )
    assert response.status_code == 403
    assert 'Not allowed' in response.json()['detail']


@readonly_db
def test_patch_workspace_not_found(workspaces_client):
    """PATCH unknown workspace id returns 404."""
    c = workspaces_client['client']
    tok = workspaces_client['token']
    response = c.patch(
        '/workspaces/999999',
        headers=bearer_headers(tok),
        json={'name': 'Missing'},
    )
    assert response.status_code == 404
    assert response.json()['detail'] == 'Workspace not found'


@readonly_db
def test_patch_workspace_forbidden_for_non_member(workspaces_client):
    """User who is not a member cannot PATCH another workspace."""
    c = workspaces_client['client']
    tok = workspaces_client['token_owner_w2']
    response = c.patch(
        f"/workspaces/{workspaces_client['w1']}",
        headers=bearer_headers(tok),
        json={'name': 'Should Not Work'},
    )
    assert response.status_code == 403
    assert 'Not allowed' in response.json()['detail']


@readonly_db
def test_get_workspaces_unauthenticated_401(workspaces_client):
    """Listing workspaces without a bearer token is rejected."""
    c = workspaces_client['client']
    response = c.get('/workspaces')
    assert response.status_code == 401
    assert response.json()['detail'] == 'Not authenticated'


@readonly_db
def test_get_workspace_by_id_unauthenticated_401(workspaces_client):
    """Fetching a workspace by id without a bearer token is rejected."""
    c = workspaces_client['client']
    response = c.get(f"/workspaces/{workspaces_client['w1']}")
    assert response.status_code == 401
    assert response.json()['detail'] == 'Not authenticated'


@readonly_db
def test_create_workspace_empty_name_422(workspaces_client):
    """Workspace name must be non-empty (Pydantic min_length=1)."""
    c = workspaces_client['client']
    tok = workspaces_client['token_instance_admin']
    response = c.post(
        '/workspaces',
        headers=bearer_headers(tok),
        json={'name': ''},
    )
    assert response.status_code == 422
    assert response.json()['detail']


@readonly_db
def test_patch_workspace_empty_name_422(workspaces_client):
    """Workspace rename rejects an empty name."""
    c = workspaces_client['client']
    tok = workspaces_client['token']
    response = c.patch(
        f"/workspaces/{workspaces_client['w1']}",
        headers=bearer_headers(tok),
        json={'name': ''},
    )
    assert response.status_code == 422
    assert response.json()['detail']
