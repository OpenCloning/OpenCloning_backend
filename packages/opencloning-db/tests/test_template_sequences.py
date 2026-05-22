"""Template sequence endpoints and template-specific behaviors."""

import pytest
from sqlalchemy.orm import Session

from opencloning_db.models import TemplateSequence

from .helpers import attach_standard_tokens, seed_standard_users, workspace_headers


@pytest.fixture
def template_sequences_client(engine_client_config):
    engine, client, _ = engine_client_config

    with Session(engine) as session:
        ctx = seed_standard_users(session)
        session.commit()

    seeded = attach_standard_tokens(ctx, client)
    seeded['engine'] = engine
    return seeded


def test_post_template_sequence_owner_ok(template_sequences_client):
    c = template_sequences_client['client']
    response = c.post(
        '/template_sequences',
        headers=workspace_headers(template_sequences_client['token_owner_w1'], template_sequences_client['w1']),
        json={'name': 'Template Allele', 'sequence_type': 'allele'},
    )
    assert response.status_code == 200
    body = response.json()
    assert body['name'] == 'Template Allele'
    assert body['type'] == 'template_sequence'
    assert body['sequence_type'] == 'allele'
    assert body['seguid'] is None
    assert body['sample_uids'] == []


def test_post_template_sequence_viewer_forbidden(template_sequences_client):
    c = template_sequences_client['client']
    response = c.post(
        '/template_sequences',
        headers=workspace_headers(template_sequences_client['token_viewer_w1'], template_sequences_client['w1']),
        json={'name': 'Template Allele', 'sequence_type': 'allele'},
    )
    assert response.status_code == 403
    assert 'Not allowed' in response.json()['detail']


def test_sequence_samples_accepts_template_sequence(template_sequences_client):
    c = template_sequences_client['client']
    headers = workspace_headers(template_sequences_client['token_owner_w1'], template_sequences_client['w1'])
    create = c.post(
        '/template_sequences',
        headers=headers,
        json={'name': 'Template Allele', 'sequence_type': 'allele'},
    )
    assert create.status_code == 200

    response = c.post(
        '/sequence_samples',
        headers=headers,
        json={'uid': 'S-TEMPLATE', 'sequence_id': create.json()['id']},
    )
    assert response.status_code == 200


def test_sequences_route_accepts_template_id(template_sequences_client):
    c = template_sequences_client['client']
    headers = workspace_headers(template_sequences_client['token_owner_w1'], template_sequences_client['w1'])
    create = c.post(
        '/template_sequences',
        headers=headers,
        json={'name': 'Template Allele', 'sequence_type': 'allele'},
    )
    assert create.status_code == 200

    response = c.get(f"/sequences/{create.json()['id']}", headers=headers)
    assert response.status_code == 200


def test_post_template_sequence_persists_template_subtype(template_sequences_client):
    engine = template_sequences_client['engine']
    c = template_sequences_client['client']
    headers = workspace_headers(template_sequences_client['token_owner_w1'], template_sequences_client['w1'])
    create = c.post(
        '/template_sequences',
        headers=headers,
        json={'name': 'Template Allele', 'sequence_type': 'allele'},
    )
    assert create.status_code == 200

    with Session(engine) as session:
        stored = session.get(TemplateSequence, create.json()['id'])

    assert stored is not None
    assert stored.name == 'Template Allele'


def test_post_template_sequence_duplicate_name_409(template_sequences_client):
    c = template_sequences_client['client']
    headers = workspace_headers(template_sequences_client['token_owner_w1'], template_sequences_client['w1'])
    first = c.post(
        '/template_sequences',
        headers=headers,
        json={'name': 'Shared Template', 'sequence_type': 'allele'},
    )
    assert first.status_code == 200

    second = c.post(
        '/template_sequences',
        headers=headers,
        json={'name': 'Shared Template', 'sequence_type': 'plasmid'},
    )
    assert second.status_code == 409
    assert 'already exists' in second.json()['detail']


def test_post_template_sequence_duplicate_name_case_insensitive_409(template_sequences_client):
    c = template_sequences_client['client']
    headers = workspace_headers(template_sequences_client['token_owner_w1'], template_sequences_client['w1'])
    first = c.post(
        '/template_sequences',
        headers=headers,
        json={'name': 'Case Template', 'sequence_type': 'allele'},
    )
    assert first.status_code == 200

    second = c.post(
        '/template_sequences',
        headers=headers,
        json={'name': 'case template', 'sequence_type': 'allele'},
    )
    assert second.status_code == 409
    assert 'already exists' in second.json()['detail']


def test_patch_template_sequence_duplicate_name_409(template_sequences_client):
    c = template_sequences_client['client']
    headers = workspace_headers(template_sequences_client['token_owner_w1'], template_sequences_client['w1'])
    first = c.post(
        '/template_sequences',
        headers=headers,
        json={'name': 'Rename Target', 'sequence_type': 'allele'},
    )
    assert first.status_code == 200
    other = c.post(
        '/template_sequences',
        headers=headers,
        json={'name': 'Other Template', 'sequence_type': 'allele'},
    )
    assert other.status_code == 200

    patch = c.patch(
        f"/sequences/{first.json()['id']}",
        headers=headers,
        json={'name': 'other template'},
    )
    assert patch.status_code == 409
    assert 'already exists' in patch.json()['detail']


def test_post_template_sequence_same_name_different_workspace_ok(template_sequences_client):
    c = template_sequences_client['client']
    w1_headers = workspace_headers(template_sequences_client['token_owner_w1'], template_sequences_client['w1'])
    w2_headers = workspace_headers(template_sequences_client['token_owner_w2'], template_sequences_client['w2'])
    w1 = c.post(
        '/template_sequences',
        headers=w1_headers,
        json={'name': 'Cross Workspace', 'sequence_type': 'allele'},
    )
    assert w1.status_code == 200
    w2 = c.post(
        '/template_sequences',
        headers=w2_headers,
        json={'name': 'Cross Workspace', 'sequence_type': 'allele'},
    )
    assert w2.status_code == 200


def test_change_circularity_rejects_template_sequence(template_sequences_client):
    """Endpoints guarded by require_real_sequence return 404 for template sequences."""
    c = template_sequences_client['client']
    headers = workspace_headers(template_sequences_client['token_owner_w1'], template_sequences_client['w1'])
    create = c.post('/template_sequences', headers=headers, json={'name': 'name', 'sequence_type': 'allele'})
    assert create.status_code == 200
    tid = create.json()['id']

    r = c.patch(f'/sequences/{tid}/change_circularity', headers=headers)
    assert r.status_code == 404
