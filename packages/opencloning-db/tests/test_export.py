"""Workspace export endpoint."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from opencloning_db.context import WriteContext
from opencloning_db.db import cloning_strategy_to_db
from opencloning_db.models import Line, Primer, Sequence, SequenceType, Tag, TemplateSequence, User
from tests.cloning_strategy_examples import cs_pcr

from .helpers import (
    assert_get_invalid_workspace_id_422,
    assert_get_missing_workspace_header_422,
    assert_get_non_member_workspace_403,
    assert_get_unauthenticated_401,
    attach_standard_tokens,
    seed_standard_users,
    workspace_headers,
)


@pytest.fixture
def export_client(request):
    """Seed read-only or write DB based on ``readonly_db`` marker."""
    if request.node.get_closest_marker('readonly_db'):
        return request.getfixturevalue('_export_client_readonly')
    engine, client, _ = request.getfixturevalue('engine_client_config_write')
    return attach_standard_tokens(_seed_export_context(engine), client)


@pytest.fixture(scope='module')
def _export_client_readonly(engine_client_config_readonly):
    engine, client, _ = engine_client_config_readonly
    return attach_standard_tokens(_seed_export_context(engine), client)


readonly_db = pytest.mark.readonly_db


def _seed_export_context(engine):
    with Session(engine) as session:
        ctx = seed_standard_users(session)
        w1_ctx = WriteContext(user=User(id=ctx['owner_w1_id'], email='unused@test'), workspace_id=ctx['w1'])
        w2_ctx = WriteContext(user=User(id=ctx['owner_w2_id'], email='unused@test'), workspace_id=ctx['w2'])

        primer_w1 = Primer(
            workspace_id=ctx['w1'],
            uid_workspace_id=ctx['w1'],
            name='primer-w1',
            sequence='ATGC',
            created_by_id=ctx['owner_w1_id'],
        )
        primer_w2 = Primer(
            workspace_id=ctx['w2'],
            uid_workspace_id=ctx['w2'],
            name='primer-w2',
            sequence='ATGC',
            created_by_id=ctx['owner_w2_id'],
        )
        line_w1 = Line(workspace_id=ctx['w1'], uid='line-w1', created_by_id=ctx['owner_w1_id'])
        line_w2 = Line(workspace_id=ctx['w2'], uid='line-w2', created_by_id=ctx['owner_w2_id'])
        tag_w1 = Tag(name='tag-w1', workspace_id=ctx['w1'])
        tag_w1_free = Tag(name='tag-w1-free', workspace_id=ctx['w1'])
        tag_w2 = Tag(name='tag-w2', workspace_id=ctx['w2'])
        seq_w1 = Sequence.from_create(
            name='seq-w1',
            file_content='seq_w1.gb',
            seguid='SEGUID-SEQ-W1',
            sequence_type=SequenceType.plasmid,
            ctx=w1_ctx,
        )
        seq_w2 = Sequence.from_create(
            name='seq-w2',
            file_content='seq_w2.gb',
            seguid='SEGUID-SEQ-W2',
            sequence_type=SequenceType.plasmid,
            ctx=w2_ctx,
        )
        template_w1 = TemplateSequence.from_create(
            name='template-w1',
            sequence_type=SequenceType.allele,
            ctx=w1_ctx,
        )
        primer_w1.tags.append(tag_w1)
        line_w1.tags.append(tag_w1)
        session.add_all(
            [primer_w1, primer_w2, line_w1, line_w2, tag_w1, tag_w1_free, tag_w2, seq_w1, seq_w2, template_w1]
        )
        session.flush()
        cloning_strategy_to_db(cs_pcr, session, ctx=w1_ctx)
        session.flush()
        pcr_product = session.scalar(
            select(Sequence).where(Sequence.workspace_id == ctx['w1'], Sequence.name == 'pcr_product')
        )
        session.commit()

        ctx.update(
            {
                'tag_w1_id': tag_w1.id,
                'tag_w1_free_id': tag_w1_free.id,
                'tag_w2_id': tag_w2.id,
                'primer_w1_id': primer_w1.id,
                'primer_w2_id': primer_w2.id,
                'line_w1_id': line_w1.id,
                'line_w2_id': line_w2.id,
                'seq_w1_id': seq_w1.id,
                'seq_w2_id': seq_w2.id,
                'template_w1_id': template_w1.id,
                'pcr_product_id': pcr_product.id,
            }
        )
    return ctx


def _get_export(client, token: str, workspace_id: int):
    return client.get('/export', headers=workspace_headers(token, workspace_id))


@readonly_db
def test_export_requires_workspace_id(export_client):
    assert_get_missing_workspace_header_422(
        export_client['client'],
        '/export',
        export_client['token_owner_w1'],
    )


@readonly_db
def test_export_invalid_workspace_id(export_client):
    assert_get_invalid_workspace_id_422(
        export_client['client'],
        '/export',
        export_client['token_owner_w1'],
    )


@readonly_db
def test_export_unauthenticated(export_client):
    assert_get_unauthenticated_401(
        export_client['client'],
        '/export',
        export_client['w1'],
    )


@readonly_db
def test_export_forbidden_non_member(export_client):
    assert_get_non_member_workspace_403(
        export_client['client'],
        '/export',
        export_client['token_owner_w2'],
        export_client['w1'],
    )


@readonly_db
def test_export_scoped_to_workspace(export_client):
    """Export includes only entities from the selected workspace."""
    c = export_client['client']
    tok = export_client['token_owner_w1']
    response = _get_export(c, tok, export_client['w1'])
    assert response.status_code == 200, response.text
    payload = response.json()

    assert {line['uid'] for line in payload['lines']} == {'line-w1'}
    primer_names = {primer['name'] for primer in payload['primers']}
    assert primer_names >= {'primer-w1', 'primer1', 'primer2'}
    sequence_names = {seq['name'] for seq in payload['sequences']}
    assert sequence_names >= {'seq-w1', 'template-w1', 'template', 'pcr_product'}
    assert {tag['name'] for tag in payload['tags']} == {'tag-w1', 'tag-w1-free'}

    w2_uids = {item['uid'] for item in payload['lines']}
    w2_primers = {item['name'] for item in payload['primers']}
    w2_sequences = {item['name'] for item in payload['sequences']}
    w2_tags = {item['name'] for item in payload['tags']}
    assert 'line-w2' not in w2_uids
    assert 'primer-w2' not in w2_primers
    assert 'seq-w2' not in w2_sequences
    assert 'tag-w2' not in w2_tags


@readonly_db
def test_export_users_are_workspace_members(export_client):
    """Users list contains workspace members as UserRef."""
    c = export_client['client']
    tok = export_client['token_owner_w1']
    response = _get_export(c, tok, export_client['w1'])
    assert response.status_code == 200, response.text
    users = response.json()['users']

    assert len(users) == 4
    assert all(set(user) == {'id', 'display_name'} for user in users)
    display_names = {user['display_name'] for user in users}
    assert display_names == {
        'Owner W1',
        'Viewer W1',
        'Owner Both',
        'Owner W1 Viewer W2',
    }

    response_w2 = _get_export(c, export_client['token_owner_w2'], export_client['w2'])
    assert response_w2.status_code == 200, response_w2.text
    users_w2 = response_w2.json()['users']
    assert len(users_w2) == 3
    assert {user['display_name'] for user in users_w2} == {
        'Owner W2',
        'Owner Both',
        'Owner W1 Viewer W2',
    }


@readonly_db
def test_export_uses_id_refs_not_nested_copies(export_client):
    """Exported entity refs use ids for related objects defined at the top level."""
    c = export_client['client']
    tok = export_client['token_owner_w1']
    payload = _get_export(c, tok, export_client['w1']).json()

    line = next(item for item in payload['lines'] if item['uid'] == 'line-w1')
    primer = next(item for item in payload['primers'] if item['name'] == 'primer-w1')
    sequence = next(item for item in payload['sequences'] if item['name'] == 'seq-w1')

    assert line['tag_ids'] == [export_client['tag_w1_id']]
    assert line['created_by_id'] == export_client['owner_w1_id']
    assert line['sequence_ids'] == []
    assert 'tags' not in line
    assert 'created_by' not in line

    assert primer['tag_ids'] == [export_client['tag_w1_id']]
    assert primer['created_by_id'] == export_client['owner_w1_id']
    assert 'tags' not in primer
    assert 'created_by' not in primer

    assert sequence['tag_ids'] == []
    assert sequence['created_by_id'] == export_client['owner_w1_id']
    assert sequence['seguid'] == 'SEGUID-SEQ-W1'
    assert 'tags' not in sequence
    assert 'created_by' not in sequence
    assert 'file_content' not in sequence

    tag_ids = {tag['id'] for tag in payload['tags']}
    user_ids = {user['id'] for user in payload['users']}
    assert line['tag_ids'][0] in tag_ids
    assert line['created_by_id'] in user_ids


@readonly_db
def test_export_cloning_strategies_from_leaf_sequences(export_client):
    """Leaf sequences contribute merged, deduplicated cloning strategy data."""
    c = export_client['client']
    tok = export_client['token_owner_w1']
    headers = workspace_headers(tok, export_client['w1'])

    payload = _get_export(c, tok, export_client['w1']).json()
    exported = payload['cloning_strategies']

    strategy_r = c.get(
        f"/sequences/{export_client['pcr_product_id']}/cloning_strategy",
        headers=headers,
        params={'recursive': True},
    )
    assert strategy_r.status_code == 200, strategy_r.text
    expected = strategy_r.json()

    assert {seq['id'] for seq in exported['sequences']} == {seq['id'] for seq in expected['sequences']}
    assert {source['id'] for source in exported['sources']} == {source['id'] for source in expected['sources']}
    assert {primer['id'] for primer in exported['primers']} == {primer['id'] for primer in expected['primers']}
    assert len(exported['sequences']) == len(expected['sequences']) == 2
    assert len(exported['sources']) == len(expected['sources']) == 2
    assert len(exported['primers']) == len(expected['primers']) == 2
