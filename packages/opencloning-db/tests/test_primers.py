"""Primers routes: workspace scoping and membership."""

import pytest
from sqlalchemy.orm import Session

from opencloning_db.models import AssemblyFragment, Primer, Sequence, SequenceType, Source, SourceType, Tag

from .helpers import (
    assert_get_invalid_workspace_id_422,
    assert_get_missing_workspace_header_422,
    assert_get_non_member_workspace_403,
    assert_get_unauthenticated_401,
    assert_post_unauthenticated_401,
    attach_standard_tokens,
    seed_standard_users,
    workspace_headers,
)


@pytest.fixture
def primers_client(engine_client_config):
    """Fresh DB with W1/W2; seeded primer on W1."""
    engine, client, _ = engine_client_config

    with Session(engine) as session:
        ctx = seed_standard_users(session)

        primer = Primer(
            workspace_id=ctx['w1'],
            uid_workspace_id=ctx['w1'],
            name='seed_primer',
            sequence='ATGC',
        )
        primer_uid = Primer(
            workspace_id=ctx['w1'],
            uid_workspace_id=ctx['w1'],
            uid='UID-PRIMER-1',
            name='uid_primer',
            sequence='CCGG',
        )
        primer_tagged = Primer(
            workspace_id=ctx['w1'],
            uid_workspace_id=ctx['w1'],
            name='tagged_primer',
            sequence='TTAA',
        )
        primer_w2 = Primer(
            workspace_id=ctx['w2'],
            uid_workspace_id=ctx['w2'],
            name='w2_primer',
            sequence='GCGC',
        )
        primer_w2_b = Primer(
            workspace_id=ctx['w2'],
            uid_workspace_id=ctx['w2'],
            name='w2_primer_b',
            sequence='ATAT',
        )
        tag_w1 = Tag(name='primer-tag-w1', workspace_id=ctx['w1'])
        primer_tagged.tags.append(tag_w1)
        template_seq = Sequence(
            workspace_id=ctx['w1'],
            name='template-seq',
            file_path='template_seq.gb',
            sequence_type=SequenceType.allele,
            seguid='SEGUID-TEMPLATE-SEQ',
        )
        product_seq = Sequence(
            workspace_id=ctx['w1'],
            name='product-seq',
            file_path='product_seq.gb',
            sequence_type=SequenceType.pcr_product,
            seguid='SEGUID-PRODUCT-SEQ',
        )
        template_seq_w2 = Sequence(
            workspace_id=ctx['w2'],
            name='template-seq-w2',
            file_path='template_seq_w2.gb',
            sequence_type=SequenceType.allele,
            seguid='SEGUID-TEMPLATE-SEQ-W2',
        )
        product_seq_w2 = Sequence(
            workspace_id=ctx['w2'],
            name='product-seq-w2',
            file_path='product_seq_w2.gb',
            sequence_type=SequenceType.pcr_product,
            seguid='SEGUID-PRODUCT-SEQ-W2',
        )
        session.add_all(
            [
                primer,
                primer_uid,
                primer_tagged,
                primer_w2,
                primer_w2_b,
                tag_w1,
                template_seq,
                product_seq,
                template_seq_w2,
                product_seq_w2,
            ]
        )
        session.flush()
        source = Source(
            type=SourceType.PCRSource,
            output_sequence=product_seq,
            input=[
                AssemblyFragment(
                    type='assembly_fragment',
                    input_entity=primer,
                    left_location='1..20',
                    right_location=None,
                    reverse_complemented=False,
                ),
                AssemblyFragment(
                    type='assembly_fragment',
                    input_entity=template_seq,
                    left_location='1..20',
                    right_location='200..220',
                    reverse_complemented=False,
                ),
                AssemblyFragment(
                    type='assembly_fragment',
                    input_entity=primer_uid,
                    left_location=None,
                    right_location='1..20',
                    reverse_complemented=True,
                ),
            ],
            extra_fields={},
        )
        source_w2 = Source(
            type=SourceType.PCRSource,
            output_sequence=product_seq_w2,
            input=[
                AssemblyFragment(
                    type='assembly_fragment',
                    input_entity=primer_w2,
                    left_location='1..20',
                    right_location=None,
                    reverse_complemented=False,
                ),
                AssemblyFragment(
                    type='assembly_fragment',
                    input_entity=template_seq_w2,
                    left_location='1..200',
                    right_location='1..200',
                    reverse_complemented=False,
                ),
                AssemblyFragment(
                    type='assembly_fragment',
                    input_entity=primer_w2_b,
                    left_location=None,
                    right_location='181..200',
                    reverse_complemented=True,
                ),
            ],
            extra_fields={},
        )
        session.add_all([source, source_w2])
        session.commit()

        ctx.update(
            {
                'primer_id': primer.id,
                'primer_uid_id': primer_uid.id,
                'primer_tagged_id': primer_tagged.id,
                'primer_w2_id': primer_w2.id,
                'tag_w1_id': tag_w1.id,
                'template_seq_id': template_seq.id,
                'product_seq_id': product_seq.id,
                'template_seq_w2_id': template_seq_w2.id,
                'product_seq_w2_id': product_seq_w2.id,
            }
        )

    return attach_standard_tokens(ctx, client)


_VALID_PRIMER_JSON = {
    'name': 'new',
    'sequence': 'GGCC',
}


def test_get_primers_requires_workspace_id(primers_client):
    """GET /primers without X-Workspace-Id fails validation (422)."""
    assert_get_missing_workspace_header_422(
        primers_client['client'],
        '/primers',
        primers_client['token_owner_w1'],
    )


def test_get_primers_lists_scoped_primers(primers_client):
    """Listed primers belong only to the selected workspace."""
    c = primers_client['client']
    wid = primers_client['w1']
    r = c.get('/primers', headers=workspace_headers(primers_client['token_owner_w1'], wid))
    assert r.status_code == 200
    data = r.json()
    ids = {it['id'] for it in data['items']}
    assert ids == {
        primers_client['primer_id'],
        primers_client['primer_uid_id'],
        primers_client['primer_tagged_id'],
    }


def test_get_primers_filter_by_tag(primers_client):
    c = primers_client['client']
    r = c.get(
        f"/primers?tags={primers_client['tag_w1_id']}",
        headers=workspace_headers(primers_client['token_owner_w1'], primers_client['w1']),
    )
    assert r.status_code == 200
    ids = {it['id'] for it in r.json()['items']}
    assert ids == {primers_client['primer_tagged_id']}


def test_get_primers_filter_by_name(primers_client):
    c = primers_client['client']
    r = c.get('/primers?name=SEED', headers=workspace_headers(primers_client['token_owner_w1'], primers_client['w1']))
    assert r.status_code == 200
    ids = {it['id'] for it in r.json()['items']}
    assert ids == {primers_client['primer_id']}


def test_get_primers_filter_by_uid_substring(primers_client):
    c = primers_client['client']
    r = c.get('/primers?uid=primer', headers=workspace_headers(primers_client['token_owner_w1'], primers_client['w1']))
    assert r.status_code == 200
    ids = {it['id'] for it in r.json()['items']}
    assert ids == {primers_client['primer_uid_id']}


def test_get_primers_filter_has_uid_true(primers_client):
    c = primers_client['client']
    r = c.get(
        '/primers?has_uid=true', headers=workspace_headers(primers_client['token_owner_w1'], primers_client['w1'])
    )
    assert r.status_code == 200
    ids = {it['id'] for it in r.json()['items']}
    assert ids == {primers_client['primer_uid_id']}


def test_get_primers_forbidden_other_workspace(primers_client):
    """Non-member cannot list primers using another workspace id."""
    c = primers_client['client']
    # owner_w2 tries to list primers in workspace w1
    r = c.get(
        '/primers',
        headers=workspace_headers(
            primers_client['token_owner_w2'],
            primers_client['w1'],
        ),
    )
    assert r.status_code == 403
    assert 'Not allowed' in r.json()['detail']


def test_get_primer_forbidden_cross_workspace(primers_client):
    """User not in W1 cannot GET a W1 primer with W1 header."""
    c = primers_client['client']
    pid = primers_client['primer_id']
    r = c.get(
        f"/primers/{pid}",
        headers=workspace_headers(
            primers_client['token_owner_w2'],
            primers_client['w1'],
        ),
    )
    assert r.status_code == 403
    assert 'Not allowed' in r.json()['detail']


def test_get_primer_ok(primers_client):
    """Member can fetch a primer by id in their workspace."""
    c = primers_client['client']
    pid = primers_client['primer_id']
    r = c.get(
        f"/primers/{pid}",
        headers=workspace_headers(
            primers_client['token_owner_w1'],
            primers_client['w1'],
        ),
    )
    assert r.status_code == 200
    assert r.json()['name'] == 'seed_primer'


def test_get_primer_sequences_ok(primers_client):
    c = primers_client['client']
    r = c.get(
        f"/primers/{primers_client['primer_id']}/sequences",
        headers=workspace_headers(primers_client['token_owner_w1'], primers_client['w1']),
    )
    assert r.status_code == 200
    body = r.json()
    template_ids = {item['id'] for item in body['templates']}
    product_ids = {item['id'] for item in body['products']}
    assert template_ids == {primers_client['template_seq_id']}
    assert product_ids == {primers_client['product_seq_id']}


def test_get_primer_selected_workspace_mismatch_returns_404(primers_client):
    """Primer in W1 with header W2 returns 404."""
    c = primers_client['client']
    pid = primers_client['primer_id']
    r = c.get(
        f"/primers/{pid}",
        headers=workspace_headers(
            primers_client['token_owner_both'],
            primers_client['w2'],
        ),
    )
    assert r.status_code == 404
    assert 'not found' in r.json()['detail'].lower()


def test_post_primer_viewer_forbidden(primers_client):
    """Viewer cannot POST a primer."""
    c = primers_client['client']
    wid = primers_client['w1']
    r = c.post(
        '/primers',
        headers=workspace_headers(primers_client['token_viewer_w1'], wid),
        json=_VALID_PRIMER_JSON,
    )
    assert r.status_code == 403
    assert 'Not allowed' in r.json()['detail']


def test_post_primer_editor_ok(primers_client):
    """Owner/editor can create a primer in the workspace."""
    c = primers_client['client']
    wid = primers_client['w1']
    r = c.post(
        '/primers',
        headers=workspace_headers(primers_client['token_owner_w1'], wid),
        json=_VALID_PRIMER_JSON,
    )
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {'id'}
    assert body['id'] > 0


def test_patch_primer_updates_name_only(primers_client):
    """PATCH with only name updates the primer."""
    c = primers_client['client']
    pid = primers_client['primer_uid_id']
    r = c.patch(
        f"/primers/{pid}",
        headers=workspace_headers(primers_client['token_owner_w1'], primers_client['w1']),
        json={'name': 'primer_renamed'},
    )
    assert r.status_code == 200
    # uid is unchanged when submitted is None
    assert r.json()['name'] == 'primer_renamed'
    assert r.json()['uid'] == 'UID-PRIMER-1'
    get_r = c.get(
        f"/primers/{pid}",
        headers=workspace_headers(primers_client['token_owner_w1'], primers_client['w1']),
    )
    assert get_r.status_code == 200
    assert get_r.json()['name'] == 'primer_renamed'
    assert get_r.json()['uid'] == 'UID-PRIMER-1'


def test_patch_primer_updates_uid_only(primers_client):
    """PATCH with only uid sets uid on a primer that had none."""
    c = primers_client['client']
    pid = primers_client['primer_id']
    r = c.patch(
        f"/primers/{pid}",
        headers=workspace_headers(primers_client['token_owner_w1'], primers_client['w1']),
        json={'uid': 'PATCHED-UID-ONLY'},
    )
    assert r.status_code == 200
    body = r.json()
    assert body['uid'] == 'PATCHED-UID-ONLY'
    assert body['name'] == 'seed_primer'
    get_r = c.get(
        f"/primers/{pid}",
        headers=workspace_headers(primers_client['token_owner_w1'], primers_client['w1']),
    )
    assert get_r.status_code == 200
    assert get_r.json()['uid'] == 'PATCHED-UID-ONLY'


def test_patch_primer_uid_conflict_returns_409(primers_client):
    """PATCH uid to one already used by another primer in the workspace returns 409."""
    c = primers_client['client']
    pid = primers_client['primer_id']
    r = c.patch(
        f"/primers/{pid}",
        headers=workspace_headers(primers_client['token_owner_w1'], primers_client['w1']),
        json={'uid': 'UID-PRIMER-1'},
    )
    assert r.status_code == 409
    assert 'already exists' in r.json()['detail']
    get_r = c.get(
        f"/primers/{pid}",
        headers=workspace_headers(primers_client['token_owner_w1'], primers_client['w1']),
    )
    assert get_r.status_code == 200
    assert get_r.json().get('uid') is None


@pytest.mark.parametrize('clear_payload', [{'uid': ''}, {'uid': '   '}])
def test_patch_primer_clears_uid(primers_client, clear_payload):
    """Explicit empty / whitespace / null uid in PATCH clears stored uid."""
    c = primers_client['client']
    pid = primers_client['primer_uid_id']
    headers = workspace_headers(primers_client['token_owner_w1'], primers_client['w1'])
    r = c.patch(f"/primers/{pid}", headers=headers, json=clear_payload)
    assert r.status_code == 200
    assert r.json()['uid'] is None
    get_r = c.get(f"/primers/{pid}", headers=headers)
    assert get_r.status_code == 200
    assert get_r.json().get('uid') is None


def test_unauthenticated_401(primers_client):
    """GET /primers without Authorization is rejected."""
    assert_get_unauthenticated_401(
        primers_client['client'],
        '/primers',
        primers_client['w1'],
    )


def test_get_primers_invalid_workspace_header_422(primers_client):
    """Non-integer X-Workspace-Id yields 422."""
    assert_get_invalid_workspace_id_422(
        primers_client['client'],
        '/primers',
        primers_client['token_owner_w1'],
        invalid='x',
    )


def test_get_primers_non_member_workspace_w3_forbidden_403(primers_client):
    """User with no membership in W3 cannot pass W3 as workspace header."""
    assert_get_non_member_workspace_403(
        primers_client['client'],
        '/primers',
        primers_client['token_owner_w1'],
        primers_client['w3'],
    )


def test_post_primer_unauthenticated_401(primers_client):
    """POST /primers without Authorization is rejected."""
    assert_post_unauthenticated_401(
        primers_client['client'],
        '/primers',
        primers_client['w1'],
        json=_VALID_PRIMER_JSON,
    )


def test_post_primer_invalid_json_422(primers_client):
    """Malformed JSON body yields 422."""
    c = primers_client['client']
    r = c.post(
        '/primers',
        headers=workspace_headers(
            primers_client['token_owner_w1'],
            primers_client['w1'],
            extra={'Content-Type': 'application/json'},
        ),
        content=b'not valid json{',
    )
    assert r.status_code == 422
    assert r.json()['detail']


def test_post_primer_empty_sequence_rejected_422(primers_client):
    """Empty primer sequence fails request validation (422)."""
    c = primers_client['client']
    body = {**_VALID_PRIMER_JSON, 'name': 'empty-seq', 'sequence': ''}
    r = c.post(
        '/primers',
        headers=workspace_headers(
            primers_client['token_owner_w1'],
            primers_client['w1'],
        ),
        json=body,
    )
    assert r.status_code == 422
    assert r.json()['detail']


def test_post_primer_wrong_sequence_rejected(primers_client):
    """One-base sequence passes linkml validation but is rejected by the ORM on create."""
    c = primers_client['client']
    body = {'name': 'one-base', 'sequence': 'A'}

    resp = c.post(
        '/primers',
        headers=workspace_headers(
            primers_client['token_owner_w1'],
            primers_client['w1'],
        ),
        json=body,
    )

    assert resp.status_code == 422

    body = {'name': 'one-base', 'sequence': 'ANAAAAAAAG'}
    resp = c.post(
        '/primers',
        headers=workspace_headers(
            primers_client['token_owner_w1'],
            primers_client['w1'],
        ),
        json=body,
    )
    assert resp.status_code == 422


def test_post_primer_repeated_uid_returns_409(primers_client):
    """POSTing a primer with a repeated UID returns 409."""
    c = primers_client['client']
    body = {**_VALID_PRIMER_JSON, 'uid': 'UID-PRIMER-1'}
    r = c.post(
        '/primers',
        headers=workspace_headers(primers_client['token_owner_w1'], primers_client['w1']),
        json=body,
    )
    assert r.status_code == 409
    assert 'already exists' in r.json()['detail']


def test_validate_upload_returns_primer_refs_with_flags(primers_client):
    c = primers_client['client']
    headers = workspace_headers(primers_client['token_viewer_w1'], primers_client['w1'])
    payload = [
        {'name': ' seed_primer ', 'sequence': 'atgc', 'uid': ' uid-primer-1 '},
        {'name': 'dup_name', 'sequence': 'GGGG', 'uid': 'X-1'},
        {'name': ' DUP_NAME ', 'sequence': 'gggg', 'uid': ' x-1 '},
        {'name': 'fresh', 'sequence': 'TATA', 'uid': None},
    ]

    r = c.post('/primers/validate-upload', headers=headers, json=payload)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 4

    assert rows[0]['name_exists'] is True
    assert rows[0]['sequence_exists'] is True
    assert rows[0]['uid_exists'] is True
    assert rows[0]['sequence_invalid'] is False
    assert rows[0]['name_duplicated'] is False
    assert rows[0]['sequence_duplicated'] is False
    assert rows[0]['uid_duplicated'] is False

    assert rows[1]['name_exists'] is False
    assert rows[1]['sequence_exists'] is False
    assert rows[1]['uid_exists'] is False
    assert rows[1]['sequence_invalid'] is False
    assert rows[1]['name_duplicated'] is True
    assert rows[1]['sequence_duplicated'] is True
    assert rows[1]['uid_duplicated'] is True

    assert rows[2]['name_exists'] is False
    assert rows[2]['sequence_exists'] is False
    assert rows[2]['uid_exists'] is False
    assert rows[2]['sequence_invalid'] is False
    assert rows[2]['name_duplicated'] is True
    assert rows[2]['sequence_duplicated'] is True
    assert rows[2]['uid_duplicated'] is True

    assert rows[3]['name_exists'] is False
    assert rows[3]['sequence_exists'] is False
    assert rows[3]['uid_exists'] is False
    assert rows[3]['sequence_invalid'] is False
    assert rows[3]['name_duplicated'] is False
    assert rows[3]['sequence_duplicated'] is False
    assert rows[3]['uid_duplicated'] is False


def test_validate_upload_flags_invalid_sequence(primers_client):
    c = primers_client['client']
    headers = workspace_headers(primers_client['token_viewer_w1'], primers_client['w1'])
    payload = [
        {'name': 'bad_char', 'sequence': 'AXTT', 'uid': None},
        {'name': 'too_short', 'sequence': 'AT', 'uid': None},
        {'name': 'ok_seq', 'sequence': 'ATG', 'uid': None},
    ]

    r = c.post('/primers/validate-upload', headers=headers, json=payload)
    assert r.status_code == 200
    rows = r.json()
    assert rows[0]['sequence_invalid'] is True
    assert rows[1]['sequence_invalid'] is True
    assert rows[2]['sequence_invalid'] is False


def test_post_primers_bulk_success_returns_primer_refs(primers_client):
    c = primers_client['client']
    headers = workspace_headers(primers_client['token_owner_w1'], primers_client['w1'])
    payload = [
        {'name': 'bulk_new_1', 'sequence': 'AACC', 'uid': 'BULK-UID-1'},
        {'name': 'bulk_new_2', 'sequence': 'GGTT', 'uid': None},
    ]

    r = c.post('/primers/bulk', headers=headers, json=payload)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    assert set(rows[0]) == {'id', 'name', 'sequence', 'uid', 'tags'}
    assert set(rows[1]) == {'id', 'name', 'sequence', 'uid', 'tags'}
    assert rows[0]['id'] > 0
    assert rows[1]['id'] > 0
    assert rows[0]['name'] == 'bulk_new_1'
    assert rows[0]['sequence'] == 'AACC'
    assert rows[0]['uid'] == 'BULK-UID-1'
    assert rows[1]['name'] == 'bulk_new_2'
    assert rows[1]['sequence'] == 'GGTT'
    assert rows[1]['uid'] is None


def test_post_primers_bulk_conflict_returns_409_and_is_atomic(primers_client):
    c = primers_client['client']
    headers = workspace_headers(primers_client['token_owner_w1'], primers_client['w1'])
    payload = [
        {'name': 'seed_primer', 'sequence': 'AACC', 'uid': 'UNUSED-NEW-UID'},
        {'name': 'would_be_created', 'sequence': 'GGTT', 'uid': 'BULK-ATOMIC-1'},
    ]

    r = c.post('/primers/bulk', headers=headers, json=payload)
    assert r.status_code == 409
    rows = r.json()
    assert len(rows) == 2
    assert rows[0]['name_exists'] is True
    assert rows[1]['name_exists'] is False
    assert rows[0]['name_duplicated'] is False
    assert rows[1]['name_duplicated'] is False

    list_r = c.get('/primers?name=would_be_created', headers=headers)
    assert list_r.status_code == 200
    assert len(list_r.json()['items']) == 0


def test_post_primers_bulk_invalid_sequence_returns_409_and_is_atomic(primers_client):
    c = primers_client['client']
    headers = workspace_headers(primers_client['token_owner_w1'], primers_client['w1'])
    payload = [
        {'name': 'invalid_seq', 'sequence': 'AT', 'uid': 'BULK-BAD-1'},
        {'name': 'would_not_be_created', 'sequence': 'GGTT', 'uid': 'BULK-BAD-2'},
    ]

    r = c.post('/primers/bulk', headers=headers, json=payload)
    assert r.status_code == 409
    rows = r.json()
    assert len(rows) == 2
    assert rows[0]['sequence_invalid'] is True
    assert rows[1]['sequence_invalid'] is False

    list_r = c.get('/primers?name=would_not_be_created', headers=headers)
    assert list_r.status_code == 200
    assert len(list_r.json()['items']) == 0


def test_post_primers_bulk_non_strict_allows_name_and_sequence_conflicts(primers_client):
    c = primers_client['client']
    headers = workspace_headers(primers_client['token_owner_w1'], primers_client['w1'])
    payload = [
        {'name': 'seed_primer', 'sequence': 'AACC', 'uid': 'NON-STRICT-UID-1'},
        {'name': 'fresh_non_strict', 'sequence': 'ATGC', 'uid': 'NON-STRICT-UID-2'},
        {'name': 'same_name', 'sequence': 'GGGGG', 'uid': 'NON-STRICT-UID-3'},
        {'name': 'same_name', 'sequence': 'GGGGG', 'uid': 'NON-STRICT-UID-4'},
    ]

    r = c.post('/primers/bulk?strict=false', headers=headers, json=payload)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 4
    assert rows[0]['name'] == 'seed_primer'
    assert rows[1]['sequence'] == 'ATGC'
    assert rows[2]['name'] == 'same_name'
    assert rows[3]['name'] == 'same_name'

    list_r = c.get('/primers?uid=NON-STRICT-UID', headers=headers)
    assert list_r.status_code == 200
    assert len(list_r.json()['items']) == 4


def test_post_primers_bulk_non_strict_still_rejects_uid_and_invalid_sequence(primers_client):
    c = primers_client['client']
    headers = workspace_headers(primers_client['token_owner_w1'], primers_client['w1'])
    ok_payload = [{'name': 'non_strict_ok', 'sequence': 'GGTT', 'uid': 'NON-STRICT-OK'}]
    for wrong_payload in [
        [{'name': 'non_strict_bad_uid', 'sequence': 'AAAAAAAAAAA', 'uid': 'UID-PRIMER-1'}],  # Existing UID
        [{'name': 'non_strict_bad_seq', 'sequence': 'AX', 'uid': 'NON-STRICT'}],  # Invalid sequence
        [{'name': 'non_strict_duplicated_UID', 'sequence': 'AAA', 'uid': 'NON-STRICT-OK'}],  # Duplicated name
    ]:
        payload = ok_payload + wrong_payload
        r = c.post('/primers/bulk?strict=false', headers=headers, json=payload)
        assert r.status_code == 409
        list_r = c.get('/primers?name=non_strict', headers=headers)
        assert list_r.status_code == 200
        assert len(list_r.json()['items']) == 0
