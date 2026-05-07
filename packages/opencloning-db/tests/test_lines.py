"""Lines routes: workspace scoping and membership."""

import pytest
from sqlalchemy.orm import Session

from opencloning_db.models import Line, Sequence, SequenceInLine, SequenceType, Tag

from .helpers import (
    assert_get_invalid_workspace_id_422,
    assert_get_missing_workspace_header_422,
    assert_get_non_member_workspace_403,
    assert_get_unauthenticated_401,
    assert_patch_unauthenticated_401,
    assert_post_unauthenticated_401,
    attach_standard_tokens,
    seed_standard_users,
    workspace_headers,
)


@pytest.fixture
def lines_client(engine_client_config):
    """Fresh DB for lines workspace authorization tests."""
    engine, client, _ = engine_client_config

    with Session(engine) as session:
        ctx = seed_standard_users(session)

        allele_w1 = Sequence(
            workspace_id=ctx['w1'],
            name='allele-w1',
            file_path='allele_w1.gb',
            sequence_type=SequenceType.allele,
            seguid='SEGUID-ALLELE-W1',
        )
        plasmid_w1 = Sequence(
            workspace_id=ctx['w1'],
            name='plasmid-w1',
            file_path='plasmid_w1.gb',
            sequence_type=SequenceType.plasmid,
            seguid='SEGUID-PLASMID-W1',
        )
        allele_w1_aux = Sequence(
            workspace_id=ctx['w1'],
            name='allele-aux',
            file_path='allele_aux.gb',
            sequence_type=SequenceType.allele,
            seguid='SEGUID-ALLELE-AUX',
        )
        allele_w2 = Sequence(
            workspace_id=ctx['w2'],
            name='allele-w2',
            file_path='allele_w2.gb',
            sequence_type=SequenceType.allele,
            seguid='SEGUID-ALLELE-W2',
        )
        plasmid_w2 = Sequence(
            workspace_id=ctx['w2'],
            name='plasmid-w2',
            file_path='plasmid_w2.gb',
            sequence_type=SequenceType.plasmid,
            seguid='SEGUID-PLASMID-W2',
        )
        # Sequences for filter coverage (multi-token genotype/plasmid paths).
        allele_filter = Sequence(
            workspace_id=ctx['w1'],
            name='alpha beta',
            file_path='allele_filter.gb',
            sequence_type=SequenceType.allele,
            seguid='SEGUID-ALLELE-FILTER',
        )
        plasmid_filter = Sequence(
            workspace_id=ctx['w1'],
            name='gamma delta',
            file_path='plasmid_filter.gb',
            sequence_type=SequenceType.plasmid,
            seguid='SEGUID-PLASMID-FILTER',
        )
        session.add_all(
            [
                allele_w1,
                plasmid_w1,
                allele_w1_aux,
                allele_w2,
                plasmid_w2,
                allele_filter,
                plasmid_filter,
            ]
        )
        session.flush()

        line_w1 = Line(workspace_id=ctx['w1'], uid='L-W1')
        line_w2 = Line(workspace_id=ctx['w2'], uid='L-W2')
        line_filter = Line(workspace_id=ctx['w1'], uid='L-FILTER')
        line_filter.sequences_in_line = [
            SequenceInLine(sequence=allele_filter),
            SequenceInLine(sequence=plasmid_filter),
        ]
        line_parent_to_be_added = Line(workspace_id=ctx['w1'], uid='L-PARENT-TO-BE-ADDED')
        line_seeded_parented = Line(workspace_id=ctx['w1'], uid='L-SEEDED-PARENTED')
        line_seeded_parented.parents = [line_w1]
        line_seeded_parented.sequences_in_line = [
            SequenceInLine(sequence=allele_w1),
            SequenceInLine(sequence=plasmid_w1),
        ]
        line_tagged = Line(workspace_id=ctx['w1'], uid='L-TAGGED')
        tag_filter = Tag(name='line-filter-tag', workspace_id=ctx['w1'])
        line_tagged.tags.append(tag_filter)
        session.add_all(
            [line_w1, line_w2, line_filter, line_parent_to_be_added, line_seeded_parented, line_tagged, tag_filter]
        )
        session.commit()

        ctx.update(
            {
                'line_w1_id': line_w1.id,
                'line_filter_id': line_filter.id,
                'line_with_parent_to_be_added': line_parent_to_be_added.id,
                'line_seeded_parented_id': line_seeded_parented.id,
                'line_tagged_id': line_tagged.id,
                'tag_filter_id': tag_filter.id,
                'allele_w1_id': allele_w1.id,
                'allele_w1_aux_id': allele_w1_aux.id,
                'plasmid_w1_id': plasmid_w1.id,
                'allele_w2_id': allele_w2.id,
                'plasmid_w2_id': plasmid_w2.id,
            }
        )

    return attach_standard_tokens(ctx, client)


def test_get_lines_requires_workspace_id(lines_client):
    """GET /lines without X-Workspace-Id fails validation (422)."""
    assert_get_missing_workspace_header_422(
        lines_client['client'],
        '/lines',
        lines_client['token_owner_w1'],
    )


def test_get_lines_scoped_to_workspace(lines_client):
    """Pagination returns only lines in the selected workspace."""
    c = lines_client['client']
    token = lines_client['token_owner_w1']
    w1 = lines_client['w1']
    response = c.get('/lines', headers=workspace_headers(token, w1))
    assert response.status_code == 200
    items = response.json()['items']
    ids = [item['id'] for item in items]
    assert set(ids) == {
        lines_client['line_w1_id'],
        lines_client['line_filter_id'],
        lines_client['line_with_parent_to_be_added'],
        lines_client['line_seeded_parented_id'],
        lines_client['line_tagged_id'],
    }
    assert ids == sorted(ids, reverse=True)


def test_get_lines_filter_by_tag(lines_client):
    c = lines_client['client']
    response = c.get(
        f"/lines?tags={lines_client['tag_filter_id']}",
        headers=workspace_headers(lines_client['token_owner_w1'], lines_client['w1']),
    )
    assert response.status_code == 200
    ids = {item['id'] for item in response.json()['items']}
    assert ids == {lines_client['line_tagged_id']}


def test_get_lines_filter_by_genotype_tokens(lines_client):
    c = lines_client['client']
    response = c.get(
        '/lines?genotype=alpha%20BETA',
        headers=workspace_headers(lines_client['token_owner_w1'], lines_client['w1']),
    )
    assert response.status_code == 200
    ids = {item['id'] for item in response.json()['items']}
    assert ids == {lines_client['line_filter_id']}


def test_get_lines_filter_by_plasmid_tokens(lines_client):
    c = lines_client['client']
    response = c.get(
        '/lines?plasmid=gamma%20delta',
        headers=workspace_headers(lines_client['token_owner_w1'], lines_client['w1']),
    )
    assert response.status_code == 200
    ids = {item['id'] for item in response.json()['items']}
    assert ids == {lines_client['line_filter_id']}


def test_get_lines_filter_by_uid(lines_client):
    c = lines_client['client']
    response = c.get(
        '/lines?uid=FILTER',
        headers=workspace_headers(lines_client['token_owner_w1'], lines_client['w1']),
    )
    assert response.status_code == 200
    ids = {item['id'] for item in response.json()['items']}
    assert ids == {lines_client['line_filter_id']}


def test_get_lines_filter_by_uid_and_plasmid(lines_client):
    c = lines_client['client']
    response = c.get(
        '/lines?uid=FILTER&plasmid=gamma%20delta',
        headers=workspace_headers(lines_client['token_owner_w1'], lines_client['w1']),
    )
    assert response.status_code == 200
    ids = {item['id'] for item in response.json()['items']}
    assert ids == {lines_client['line_filter_id']}


def test_get_lines_forbidden_for_non_member(lines_client):
    """Non-member cannot list lines with another workspace header."""
    c = lines_client['client']
    token = lines_client['token_owner_w2']
    response = c.get('/lines', headers=workspace_headers(token, lines_client['w1']))
    assert response.status_code == 403
    assert 'Not allowed' in response.json()['detail']


def test_get_line_forbidden_cross_workspace(lines_client):
    """User not in W1 cannot GET a W1 line with W1 header."""
    c = lines_client['client']
    token = lines_client['token_owner_w2']
    response = c.get(f"/lines/{lines_client['line_w1_id']}", headers=workspace_headers(token, lines_client['w1']))
    assert response.status_code == 403
    assert 'Not allowed' in response.json()['detail']


def test_get_line_selected_workspace_mismatch_returns_404(lines_client):
    """Line in W1 with header W2 returns 404."""
    c = lines_client['client']
    token = lines_client['token_owner_both']
    response = c.get(f"/lines/{lines_client['line_w1_id']}", headers=workspace_headers(token, lines_client['w2']))
    assert response.status_code == 404
    assert response.json()['detail'] == 'Line not found'


def test_get_line_ok(lines_client):
    c = lines_client['client']
    response = c.get(
        f"/lines/{lines_client['line_filter_id']}",
        headers=workspace_headers(lines_client['token_owner_w1'], lines_client['w1']),
    )
    assert response.status_code == 200
    body = response.json()
    assert body['uid'] == 'L-FILTER'
    names = {item['sequence']['name'] for item in body['sequences_in_line']}
    assert names == {'alpha beta', 'gamma delta'}


def test_get_line_seeded_parent_ids_ok(lines_client):
    c = lines_client['client']
    response = c.get(
        f"/lines/{lines_client['line_seeded_parented_id']}",
        headers=workspace_headers(lines_client['token_owner_w1'], lines_client['w1']),
    )
    assert response.status_code == 200
    assert response.json()['parent_ids'] == [lines_client['line_w1_id']]


def test_get_line_children_ok(lines_client):
    c = lines_client['client']
    response = c.get(
        f"/lines/{lines_client['line_w1_id']}/children",
        headers=workspace_headers(lines_client['token_owner_w1'], lines_client['w1']),
    )
    assert response.status_code == 200
    ids = {item['id'] for item in response.json()}
    assert ids == {lines_client['line_seeded_parented_id']}


def test_get_line_children_empty_ok(lines_client):
    c = lines_client['client']
    response = c.get(
        f"/lines/{lines_client['line_with_parent_to_be_added']}/children",
        headers=workspace_headers(lines_client['token_owner_w1'], lines_client['w1']),
    )
    assert response.status_code == 200
    assert response.json() == []


def test_post_line_viewer_forbidden(lines_client):
    """Viewer cannot create a line."""
    c = lines_client['client']
    token = lines_client['token_viewer_w1']
    response = c.post(
        '/lines',
        headers=workspace_headers(token, lines_client['w1']),
        json={
            'uid': 'L-NEW-VIEWER',
            'allele_ids': [],
            'plasmid_ids': [],
            'parent_ids': [],
        },
    )
    assert response.status_code == 403
    assert 'Not allowed' in response.json()['detail']


def test_post_line_owner_ok(lines_client):
    """Owner can create a line with sequences from the same workspace."""
    c = lines_client['client']
    token = lines_client['token_owner_w1']
    response = c.post(
        '/lines',
        headers=workspace_headers(token, lines_client['w1']),
        json={
            'uid': 'L-NEW-OWNER',
            'allele_ids': [lines_client['allele_w1_id']],
            'plasmid_ids': [lines_client['plasmid_w1_id']],
            'parent_ids': [],
        },
    )
    assert response.status_code == 200
    assert response.json()['uid'] == 'L-NEW-OWNER'


def test_post_line_duplicate_uid_409(lines_client):
    c = lines_client['client']
    response = c.post(
        '/lines',
        headers=workspace_headers(lines_client['token_owner_w1'], lines_client['w1']),
        json={
            'uid': 'L-W1',
            'allele_ids': [lines_client['allele_w1_id']],
            'plasmid_ids': [lines_client['plasmid_w1_id']],
            'parent_ids': [],
        },
    )
    assert response.status_code == 409
    assert 'already exists' in response.json()['detail']


def test_post_line_with_parent_ids_ok(lines_client):
    c = lines_client['client']
    response = c.post(
        '/lines',
        headers=workspace_headers(lines_client['token_owner_w1'], lines_client['w1']),
        json={
            'uid': 'L-WITH-PARENT',
            'allele_ids': [lines_client['allele_w1_id']],
            'plasmid_ids': [lines_client['plasmid_w1_id']],
            'parent_ids': [lines_client['line_w1_id']],
        },
    )
    assert response.status_code == 200
    assert response.json()['parent_ids'] == [lines_client['line_w1_id']]


def test_patch_line_viewer_forbidden(lines_client):
    """Viewer cannot PATCH line fields."""
    c = lines_client['client']
    token = lines_client['token_viewer_w1']
    response = c.patch(
        f"/lines/{lines_client['line_w1_id']}",
        headers=workspace_headers(token, lines_client['w1']),
        json={'parent_ids': []},
    )
    assert response.status_code == 403
    assert 'Not allowed' in response.json()['detail']


def test_get_lines_invalid_workspace_header_422(lines_client):
    """Non-integer X-Workspace-Id yields 422."""
    assert_get_invalid_workspace_id_422(
        lines_client['client'],
        '/lines',
        lines_client['token_owner_w1'],
        invalid='zzz',
    )


def test_get_lines_non_member_workspace_w3_forbidden_403(lines_client):
    """User with no access to W3 cannot use W3 header on GET /lines."""
    assert_get_non_member_workspace_403(
        lines_client['client'],
        '/lines',
        lines_client['token_owner_w1'],
        lines_client['w3'],
    )


def test_get_lines_unauthenticated_401(lines_client):
    """GET /lines without Authorization is rejected."""
    assert_get_unauthenticated_401(
        lines_client['client'],
        '/lines',
        lines_client['w1'],
    )


def test_post_line_with_allele_from_other_workspace_returns_404(lines_client):
    """Reject W2 allele id when creating a line under W1 (404)."""
    c = lines_client['client']
    tok = lines_client['token_owner_both']
    response = c.post(
        '/lines',
        headers=workspace_headers(tok, lines_client['w1']),
        json={
            'uid': 'L-CROSS-ALLELE',
            'allele_ids': [lines_client['allele_w2_id']],
            'plasmid_ids': [lines_client['plasmid_w1_id']],
            'parent_ids': [],
        },
    )
    assert response.status_code == 404
    assert response.json()['detail'] == 'Sequence not found'


def test_patch_line_other_workspace_plasmid_404(lines_client):
    """PATCH cannot attach a plasmid that lives in another workspace."""
    c = lines_client['client']
    owner = lines_client['token_owner_w1']
    w1 = lines_client['w1']
    create = c.post(
        '/lines',
        headers=workspace_headers(owner, w1),
        json={
            'uid': 'L-PATCH-PLAS',
            'allele_ids': [lines_client['allele_w1_id']],
            'plasmid_ids': [lines_client['plasmid_w1_id']],
            'parent_ids': [],
        },
    )
    assert create.status_code == 200
    line_id = create.json()['id']

    both = lines_client['token_owner_both']
    response = c.patch(
        f"/lines/{line_id}",
        headers=workspace_headers(both, w1),
        json={'plasmid_ids': [lines_client['plasmid_w2_id']]},
    )
    assert response.status_code == 404
    assert response.json()['detail'] == 'Sequence not found'


def test_patch_line_alleles_success(lines_client):
    c = lines_client['client']
    response = c.patch(
        f"/lines/{lines_client['line_filter_id']}",
        headers=workspace_headers(lines_client['token_owner_w1'], lines_client['w1']),
        json={'allele_ids': [lines_client['allele_w1_aux_id']]},
    )
    assert response.status_code == 200
    allele_names = {
        item['sequence']['name']
        for item in response.json()['sequences_in_line']
        if item['sequence']['sequence_type'] == 'allele'
    }
    assert allele_names == {'allele-aux'}


def test_patch_line_plasmids_success(lines_client):
    c = lines_client['client']
    response = c.patch(
        f"/lines/{lines_client['line_filter_id']}",
        headers=workspace_headers(lines_client['token_owner_w1'], lines_client['w1']),
        json={'plasmid_ids': [lines_client['plasmid_w1_id']]},
    )
    assert response.status_code == 200
    plasmid_names = {
        item['sequence']['name']
        for item in response.json()['sequences_in_line']
        if item['sequence']['sequence_type'] == 'plasmid'
    }
    assert plasmid_names == {'plasmid-w1'}


def test_patch_line_parent_ids_success(lines_client):
    c = lines_client['client']
    response = c.patch(
        f"/lines/{lines_client['line_with_parent_to_be_added']}",
        headers=workspace_headers(lines_client['token_owner_w1'], lines_client['w1']),
        json={'parent_ids': [lines_client['line_w1_id']]},
    )
    assert response.status_code == 200
    assert response.json()['parent_ids'] == [lines_client['line_w1_id']]


def test_patch_line_uid_success(lines_client):
    c = lines_client['client']
    response = c.patch(
        f"/lines/{lines_client['line_w1_id']}",
        headers=workspace_headers(lines_client['token_owner_w1'], lines_client['w1']),
        json={'uid': 'L-W1-RENAMED'},
    )
    assert response.status_code == 200
    assert response.json()['uid'] == 'L-W1-RENAMED'

    response = c.get(
        f"/lines/{lines_client['line_w1_id']}",
        headers=workspace_headers(lines_client['token_owner_w1'], lines_client['w1']),
    )
    assert response.status_code == 200
    assert response.json()['uid'] == 'L-W1-RENAMED'


def test_patch_line_uid_duplicate_409(lines_client):
    c = lines_client['client']
    response = c.patch(
        f"/lines/{lines_client['line_w1_id']}",
        headers=workspace_headers(lines_client['token_owner_w1'], lines_client['w1']),
        json={'uid': 'L-FILTER'},
    )
    assert response.status_code == 409
    assert 'already exists' in response.json()['detail']


def test_post_line_unauthenticated_401(lines_client):
    """POST /lines without Authorization is rejected."""
    assert_post_unauthenticated_401(
        lines_client['client'],
        '/lines',
        lines_client['w1'],
        json={
            'uid': 'L-NO-AUTH',
            'allele_ids': [],
            'plasmid_ids': [],
            'parent_ids': [],
        },
    )


def test_patch_line_unauthenticated_401(lines_client):
    """PATCH /lines without Authorization is rejected."""
    assert_patch_unauthenticated_401(
        lines_client['client'],
        f"/lines/{lines_client['line_w1_id']}",
        lines_client['w1'],
        json={'parent_ids': []},
    )


def test_patch_line_self_parent_returns_400(lines_client):
    """A line cannot list itself as its own parent."""
    c = lines_client['client']
    tok = lines_client['token_owner_w1']
    lid = lines_client['line_w1_id']
    response = c.patch(
        f"/lines/{lid}",
        headers=workspace_headers(tok, lines_client['w1']),
        json={'parent_ids': [lid]},
    )
    assert response.status_code == 400
    assert 'cannot be its own parent' in response.json()['detail']


def test_delete_line_with_children_returns_409(lines_client):
    c = lines_client['client']
    response = c.delete(
        f"/lines/{lines_client['line_w1_id']}",
        headers=workspace_headers(lines_client['token_owner_w1'], lines_client['w1']),
    )
    assert response.status_code == 409
    assert 'has children' in response.json()['detail']


def test_delete_line_without_children_deletes(lines_client):
    c = lines_client['client']
    line_id = lines_client['line_seeded_parented_id']
    response = c.delete(
        f"/lines/{line_id}",
        headers=workspace_headers(lines_client['token_owner_w1'], lines_client['w1']),
    )
    assert response.status_code == 200
    assert response.json() == {'deleted': line_id, 'data': None}

    get_response = c.get(
        f"/lines/{line_id}",
        headers=workspace_headers(lines_client['token_owner_w1'], lines_client['w1']),
    )
    assert get_response.status_code == 404


def test_delete_line_does_not_exist_returns_404(lines_client):
    c = lines_client['client']
    response = c.delete(
        '/lines/999999',
        headers=workspace_headers(lines_client['token_owner_w1'], lines_client['w1']),
    )
    assert response.status_code == 404
    assert response.json()['detail'] == 'Line not found'
