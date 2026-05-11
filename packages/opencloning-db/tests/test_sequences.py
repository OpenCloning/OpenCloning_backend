"""Sequences routes: workspace scoping, filters, cloning strategy graph, and files."""

from pathlib import Path

from opencloning.dna_functions import read_dsrecord_from_json
import opencloning_linkml.datamodel.models as opencloning_models
import pytest
from pydna.dseqrecord import Dseqrecord
from pydna.dseq import Dseq
from pydna.opencloning_models import TextFileSequence
from sqlalchemy import select
from sqlalchemy.orm import Session

from opencloning_db.config import get_config
from opencloning_db.db import cloning_strategy_to_db, dseqrecord_to_db
from opencloning_db.models import Line, Sequence, SequenceInLine, SequenceSample, SequencingFile, Tag, Primer
from tests.cloning_strategy_examples import cs_gateway_BP, cs_pcr, pcr_product, pcr_template
from .helpers import (
    assert_get_invalid_workspace_id_422,
    assert_get_missing_workspace_header_422,
    assert_get_non_member_workspace_403,
    assert_get_unauthenticated_401,
    assert_patch_unauthenticated_401,
    attach_standard_tokens,
    bearer_headers,
    post_sequencing_file_upload,
    seed_standard_users,
    workspace_headers,
)
from opencloning_db.routers.sequences import _search_rotation


def _sequence_in_workspace(session: Session, workspace_id: int, name: str) -> Sequence:
    """Load a sequence by workspace id and record name (fixture / strategy lookups)."""
    row = session.scalar(select(Sequence).where(Sequence.workspace_id == workspace_id, Sequence.name == name))
    assert row is not None, f"No Sequence in workspace {workspace_id} with name {name!r}"
    return row


def _primer_in_workspace(session: Session, workspace_id: int, name: str) -> Primer:
    """Load a primer by workspace id and record name (fixture / strategy lookups)."""
    row = session.scalar(select(Primer).where(Primer.workspace_id == workspace_id, Primer.name == name))
    assert row is not None, f"No Primer in workspace {workspace_id} with name {name!r}"
    return row


@pytest.fixture
def sequences_client(engine_client_config):
    """Fresh DB with tmp sequence/sequencing dirs, bare sequences, and example cloning strategies."""
    engine, client, config = engine_client_config

    with Session(engine) as session:
        ctx = seed_standard_users(session)
        w1, w2 = ctx['w1'], ctx['w2']

        seq_w1 = dseqrecord_to_db(Dseqrecord('atgcag', name='seq-w1'), session, w1, created_by_id=ctx['owner_w1_id'])
        seq_w2 = dseqrecord_to_db(Dseqrecord('atgcagc', name='seq-w2'), session, w2, created_by_id=ctx['owner_w2_id'])

        sample_w1 = SequenceSample(
            uid='UID-W1',
            sequence_id=seq_w1.id,
            uid_workspace_id=w1,
        )
        session.add(sample_w1)

        cloning_strategy_to_db(cs_pcr, session, w1, created_by_id=ctx['owner_w1_id'])
        cloning_strategy_to_db(cs_gateway_BP, session, w1, created_by_id=ctx['owner_w1_id'])
        session.flush()

        pcr_template = _sequence_in_workspace(session, w1, 'template')
        pcr_product = _sequence_in_workspace(session, w1, 'pcr_product')
        primer1 = _primer_in_workspace(session, w1, 'primer1')
        primer2 = _primer_in_workspace(session, w1, 'primer2')
        gw_product = _sequence_in_workspace(session, w1, 'product_gateway_BP')
        attb = _sequence_in_workspace(session, w1, 'attB_input')
        attp = _sequence_in_workspace(session, w1, 'attP_input')

        tag = Tag(name='seq-filter-tag', workspace_id=w1)
        session.add(tag)
        session.flush()
        pcr_product.tags.append(tag)

        line = Line(workspace_id=w1, uid='line-for-seq-filter', created_by_id=ctx['owner_w1_id'])
        session.add(line)
        session.flush()
        session.add(SequenceInLine(sequence_id=pcr_template.id, line_id=line.id))

        session.add(
            SequenceSample(
                uid='FILTER-UID-99',
                sequence_id=pcr_product.id,
                uid_workspace_id=w1,
            )
        )

        dseqr = Dseqrecord('atgcgatcgatac', circular=True, name='circ_plasmid')
        dseqr.add_feature(0, 4, type_='CDS')
        seq_circ = dseqrecord_to_db(dseqr, session, w1, created_by_id=ctx['owner_w1_id'])
        seq_patch_linear = dseqrecord_to_db(
            Dseqrecord('atgcag', name='patch-linear-target'), session, w1, created_by_id=ctx['owner_w1_id']
        )

        seq_with_overhangs = dseqrecord_to_db(
            Dseqrecord(Dseq.from_full_sequence_and_overhangs('atgcag', 1, 1), name='with-overhangs'),
            session,
            w1,
            created_by_id=ctx['owner_w1_id'],
        )

        dseqr = Dseqrecord('ACGT', circular=True, name='with-origin-spanning-feature')
        dseqr.add_feature(0, 4, type_='CDS')
        dseqr = dseqr.shifted(2)
        dseqr.id = '0'
        seq_with_origin_spanning_feature = dseqrecord_to_db(dseqr, session, w1, created_by_id=ctx['owner_w1_id'])

        dseqr_rc = dseqr.reverse_complement()
        dseqr_rc.source = None
        seq_with_origin_spanning_feature_rc = dseqrecord_to_db(dseqr_rc, session, w1, created_by_id=ctx['owner_w1_id'])

        session.commit()

        w1_ids = set(session.scalars(select(Sequence.id).where(Sequence.workspace_id == w1)).all())
        w2_ids = set(session.scalars(select(Sequence.id).where(Sequence.workspace_id == w2)).all())

        ctx.update(
            {
                'engine': engine,
                'seq_w1_id': seq_w1.id,
                'seq_w2_id': seq_w2.id,
                'uid_w1': sample_w1.uid,
                'w1_sequence_ids': w1_ids,
                'w2_sequence_ids': w2_ids,
                'sequencing_files_dir': config.sequencing_files_dir,
                'pcr_template_id': pcr_template.id,
                'pcr_product_id': pcr_product.id,
                'pcr_product_seguid': pcr_product.seguid,
                'primer1_id': primer1.id,
                'primer2_id': primer2.id,
                'gateway_product_id': gw_product.id,
                'attb_input_id': attb.id,
                'attp_input_id': attp.id,
                'filter_tag_id': tag.id,
                'seq_circ_id': seq_circ.id,
                'seq_patch_linear_id': seq_patch_linear.id,
                'seq_with_overhangs_id': seq_with_overhangs.id,
                'seq_with_origin_spanning_feature_id': seq_with_origin_spanning_feature.id,
                'seq_with_origin_spanning_feature_rc_id': seq_with_origin_spanning_feature_rc.id,
            }
        )

    return attach_standard_tokens(ctx, client)


def test_get_sequences_requires_workspace_id(sequences_client):
    """GET /sequences without X-Workspace-Id fails validation (422)."""
    assert_get_missing_workspace_header_422(
        sequences_client['client'],
        '/sequences',
        sequences_client['token_owner_w1'],
    )


def test_get_sequences_scoped_to_workspace(sequences_client):
    """Pagination list includes all sequences in the selected workspace."""
    c = sequences_client['client']
    tok = sequences_client['token_owner_w1']
    response = c.get('/sequences', headers=workspace_headers(tok, sequences_client['w1']))
    assert response.status_code == 200
    items = response.json()['items']
    ids = [item['id'] for item in items]
    assert set(ids) == sequences_client['w1_sequence_ids']
    assert ids == sorted(ids, reverse=True)


def test_get_sequences_filter_by_tag(sequences_client):
    c = sequences_client['client']
    tid = sequences_client['filter_tag_id']
    r = c.get(
        '/sequences',
        headers=workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1']),
        params=[('tags', str(tid))],
    )
    assert r.status_code == 200
    ids = {item['id'] for item in r.json()['items']}
    assert ids == {sequences_client['pcr_product_id']}


def test_get_sequences_filter_instantiated_true(sequences_client):
    c = sequences_client['client']
    r = c.get(
        '/sequences',
        headers=workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1']),
        params={'instantiated': 'true'},
    )
    assert r.status_code == 200
    ids = {item['id'] for item in r.json()['items']}
    assert {
        sequences_client['pcr_template_id'],
        sequences_client['seq_w1_id'],
        sequences_client['pcr_product_id'],
    } == ids


def test_get_sequences_filter_instantiated_false(sequences_client):
    c = sequences_client['client']
    r = c.get(
        '/sequences',
        headers=workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1']),
        params={'instantiated': 'false'},
    )
    assert r.status_code == 200
    ids = {item['id'] for item in r.json()['items']}
    assert sequences_client['attp_input_id'] in ids
    assert sequences_client['pcr_template_id'] not in ids
    assert sequences_client['seq_w1_id'] not in ids


def test_get_sequences_filter_sequence_types(sequences_client):
    c = sequences_client['client']
    r = c.get(
        '/sequences',
        headers=workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1']),
        params=[('sequence_types', 'pcr_product')],
    )
    assert r.status_code == 200
    ids = {item['id'] for item in r.json()['items']}
    assert {sequences_client['pcr_product_id']} == ids


def test_get_sequences_filter_name(sequences_client):
    c = sequences_client['client']
    r = c.get(
        '/sequences',
        headers=workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1']),
        params={'name': 'seq-w'},
    )
    assert r.status_code == 200
    ids = {item['id'] for item in r.json()['items']}
    assert ids == {sequences_client['seq_w1_id']}


def test_get_sequences_filter_uid_substring(sequences_client):
    c = sequences_client['client']
    r = c.get(
        '/sequences',
        headers=workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1']),
        params={'uid': 'filter-UID'},
    )
    assert r.status_code == 200
    ids = {item['id'] for item in r.json()['items']}
    assert ids == {sequences_client['pcr_product_id']}


def test_get_sequences_filter_has_uid(sequences_client):
    c = sequences_client['client']
    r = c.get(
        '/sequences',
        headers=workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1']),
        params={'has_uid': 'true'},
    )
    assert r.status_code == 200
    ids = {item['id'] for item in r.json()['items']}
    assert {sequences_client['seq_w1_id'], sequences_client['pcr_product_id']} == ids


def test_get_sequences_forbidden_non_member(sequences_client):
    """Non-member cannot list sequences when passing another workspace id."""
    c = sequences_client['client']
    tok = sequences_client['token_owner_w2']
    response = c.get('/sequences', headers=workspace_headers(tok, sequences_client['w1']))
    assert response.status_code == 403
    assert 'Not allowed' in response.json()['detail']


def test_get_sequence_owner_ok(sequences_client):
    c = sequences_client['client']
    sid = sequences_client['pcr_product_id']
    r = c.get(
        f"/sequences/{sid}",
        headers=workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1']),
    )
    assert r.status_code == 200
    body = r.json()
    assert body['id'] == sid
    assert body['name'] == 'pcr_product'


def test_get_sequence_forbidden_cross_workspace(sequences_client):
    """User not in W1 cannot GET a W1 sequence even with W1 header."""
    c = sequences_client['client']
    tok = sequences_client['token_owner_w2']
    response = c.get(
        f"/sequences/{sequences_client['seq_w1_id']}", headers=workspace_headers(tok, sequences_client['w1'])
    )
    assert response.status_code == 403
    assert 'Not allowed' in response.json()['detail']


def test_get_sequence_workspace_mismatch_404(sequences_client):
    """W2 sequence with W1 header returns 404."""
    c = sequences_client['client']
    tok = sequences_client['token_owner_both']
    response = c.get(
        f"/sequences/{sequences_client['seq_w2_id']}", headers=workspace_headers(tok, sequences_client['w1'])
    )
    assert response.status_code == 404
    assert response.json()['detail'] == 'Sequence not found'


def test_patch_sequence_owner_rename_ok(sequences_client):
    c = sequences_client['client']
    sid = sequences_client['seq_patch_linear_id']
    r = c.patch(
        f"/sequences/{sid}",
        headers=workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1']),
        json={'name': 'renamed-linear'},
    )
    assert r.status_code == 200
    assert r.json()['name'] == 'renamed-linear'


def test_patch_sequence_empty_name_400(sequences_client):
    c = sequences_client['client']
    r = c.patch(
        f"/sequences/{sequences_client['seq_patch_linear_id']}",
        headers=workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1']),
        json={'name': ''},
    )
    assert r.status_code == 400
    assert r.json()['detail'] == 'Name cannot be an empty string'


def test_patch_sequence_type_linear_ok(sequences_client):
    c = sequences_client['client']
    sid = sequences_client['seq_patch_linear_id']
    r = c.patch(
        f"/sequences/{sid}",
        headers=workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1']),
        json={'sequence_type': 'pcr_product'},
    )
    assert r.status_code == 200
    assert r.json()['sequence_type'] == 'pcr_product'


def test_patch_sequence_circular_rejects_non_plasmid_type(sequences_client):
    c = sequences_client['client']
    r = c.patch(
        f"/sequences/{sequences_client['seq_circ_id']}",
        headers=workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1']),
        json={'sequence_type': 'allele'},
    )
    assert r.status_code == 400
    assert r.json()['detail'] == "Circular sequences can only have sequence_type 'plasmid'"


def test_patch_sequence_viewer_forbidden(sequences_client):
    """Viewer cannot PATCH a sequence."""
    c = sequences_client['client']
    tok = sequences_client['token_viewer_w1']
    response = c.patch(
        f"/sequences/{sequences_client['seq_w1_id']}",
        headers=workspace_headers(tok, sequences_client['w1']),
        json={'name': 'new-name'},
    )
    assert response.status_code == 403
    assert 'Not allowed' in response.json()['detail']


def test_delete_sequence_owner_removes_sample_and_files(sequences_client):
    """Owner can delete an isolated sequence; sample row and on-disk files are removed."""
    c = sequences_client['client']
    tok = sequences_client['token_owner_w1']
    wid = sequences_client['w1']
    sid = sequences_client['seq_w1_id']
    headers = workspace_headers(tok, wid)

    up = post_sequencing_file_upload(c, sid, tok, wid, 'attached.ab1', b'ABIF')
    assert up.status_code == 200
    sequencing_file_id = up.json()[0]['id']

    with Session(sequences_client['engine']) as session:
        seq = session.get(Sequence, sid)
        sequence_file_path = Path(get_config().sequence_files_dir) / seq.file_path
        sequencing_file_path = (
            Path(sequences_client['sequencing_files_dir'])
            / session.get(SequencingFile, sequencing_file_id).storage_path
        )
    assert sequence_file_path.exists()
    assert sequencing_file_path.exists()

    r = c.delete(f"/sequences/{sid}", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json() == {'deleted': sid, 'data': None}

    assert c.get(f"/sequences/{sid}", headers=headers).status_code == 404
    assert c.get(f"/sequences/by-uid/{sequences_client['uid_w1']}", headers=headers).status_code == 404
    assert not sequence_file_path.exists()
    assert not sequencing_file_path.exists()
    with Session(sequences_client['engine']) as session:
        assert session.scalar(select(SequenceSample).where(SequenceSample.sequence_id == sid)) is None
        assert session.get(SequencingFile, sequencing_file_id) is None


def test_delete_sequence_rejects_when_has_children(sequences_client):
    """Sequences used as input to another source cannot be deleted (409)."""
    c = sequences_client['client']
    r = c.delete(
        f"/sequences/{sequences_client['pcr_template_id']}",
        headers=workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1']),
    )
    assert r.status_code == 409
    assert 'child sequences' in r.json()['detail']


def test_delete_sequence_allows_when_has_parents(sequences_client):
    """Sequences produced by a source with inputs can still be deleted."""
    c = sequences_client['client']
    sid = sequences_client['pcr_product_id']
    r = c.delete(
        f"/sequences/{sid}",
        headers=workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1']),
    )
    assert r.status_code == 200
    assert r.json()['deleted'] == sequences_client['pcr_product_id']

    r = c.get(
        f"/sequences/{sid}", headers=workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1'])
    )
    assert r.status_code == 404

    # Primers and template still exist though
    r = c.get(
        f"/primers/{sequences_client['primer1_id']}",
        headers=workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1']),
    )
    assert r.status_code == 200
    r = c.get(
        f"/primers/{sequences_client['primer2_id']}",
        headers=workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1']),
    )
    assert r.status_code == 200
    r = c.get(
        f"/sequences/{sequences_client['pcr_template_id']}",
        headers=workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1']),
    )
    assert r.status_code == 200


def test_delete_sequence_rejects_when_in_strain(sequences_client):
    """Sequences linked to a strain via SequenceInLine cannot be deleted (409)."""
    c = sequences_client['client']
    sid = sequences_client['seq_patch_linear_id']
    with Session(sequences_client['engine']) as session:
        line = Line(
            workspace_id=sequences_client['w1'],
            uid='line-blocking-delete',
            created_by_id=sequences_client['owner_w1_id'],
        )
        session.add(line)
        session.flush()
        session.add(SequenceInLine(sequence_id=sid, line_id=line.id))
        session.commit()

    r = c.delete(
        f"/sequences/{sid}",
        headers=workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1']),
    )
    assert r.status_code == 409
    assert 'present in a line' in r.json()['detail']


def test_delete_sequence_viewer_forbidden(sequences_client):
    """Viewers cannot delete sequences."""
    c = sequences_client['client']
    r = c.delete(
        f"/sequences/{sequences_client['seq_patch_linear_id']}",
        headers=workspace_headers(sequences_client['token_viewer_w1'], sequences_client['w1']),
    )
    assert r.status_code == 403
    assert 'Not allowed' in r.json()['detail']


def test_delete_sequence_workspace_mismatch_404(sequences_client):
    """W2 sequence id with W1 header returns 404."""
    c = sequences_client['client']
    r = c.delete(
        f"/sequences/{sequences_client['seq_w2_id']}",
        headers=workspace_headers(sequences_client['token_owner_both'], sequences_client['w1']),
    )
    assert r.status_code == 404
    assert r.json()['detail'] == 'Sequence not found'


def _parse_dseqr(payload: dict) -> Dseqrecord:
    return read_dsrecord_from_json(TextFileSequence.model_validate(payload))


def test_change_circularity_isolated_linear_to_circular(sequences_client):
    """Isolated linear sequence toggles to circular with new GenBank file and old file removed."""
    c = sequences_client['client']
    sid = sequences_client['seq_patch_linear_id']
    headers = workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1'])
    base = Path(get_config().sequence_files_dir)

    with Session(sequences_client['engine']) as session:
        seq = session.get(Sequence, sid)
        old_relative = seq.file_path
    old_path = base / old_relative
    assert old_path.exists()

    r0 = c.get(f'/sequences/{sid}/text_file_sequence', headers=headers)
    assert r0.status_code == 200
    assert _parse_dseqr(r0.json()).seq == Dseq('atgcag'.upper())

    r = c.patch(f'/sequences/{sid}/change_circularity', headers=headers)
    assert r.status_code == 200
    assert r.json()['id'] == sid

    r1 = c.get(f'/sequences/{sid}/text_file_sequence', headers=headers)
    assert r1.status_code == 200
    assert _parse_dseqr(r1.json()).seq == Dseq('atgcag'.upper(), circular=True)

    r1_db = c.get(f'/sequences/{sid}', headers=headers)
    assert r1_db.status_code == 200
    assert r1_db.json()['sequence_type'] == 'plasmid'

    with Session(sequences_client['engine']) as session:
        seq = session.get(Sequence, sid)
        assert seq.file_path != old_relative
        new_path = base / seq.file_path

    assert not old_path.exists()
    assert new_path.exists()


def test_change_circularity_isolated_circular_to_linear(sequences_client):
    c = sequences_client['client']
    sid = sequences_client['seq_circ_id']
    headers = workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1'])
    base = Path(get_config().sequence_files_dir)

    with Session(sequences_client['engine']) as session:
        old_relative = session.get(Sequence, sid).file_path
    old_path = base / old_relative

    r0 = c.get(f'/sequences/{sid}/text_file_sequence', headers=headers)
    assert _parse_dseqr(r0.json()).seq == Dseq('atgcgatcgatac'.upper(), circular=True)

    r = c.patch(f'/sequences/{sid}/change_circularity', headers=headers)
    assert r.status_code == 200

    r1 = c.get(f'/sequences/{sid}/text_file_sequence', headers=headers)
    assert _parse_dseqr(r1.json()).seq == Dseq('atgcgatcgatac'.upper())

    r1_db = c.get(f'/sequences/{sid}', headers=headers)
    assert r1_db.status_code == 200
    assert r1_db.json()['sequence_type'] == 'linear_dna'

    with Session(sequences_client['engine']) as session:
        seq = session.get(Sequence, sid)
        new_path = base / seq.file_path
    assert not old_path.exists()
    assert new_path.exists()


def test_change_circularity_rejects_when_sequence_has_children(sequences_client):
    c = sequences_client['client']
    tid = sequences_client['pcr_template_id']
    r = c.patch(
        f'/sequences/{tid}/change_circularity',
        headers=workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1']),
    )
    assert r.status_code == 400
    assert 'child sequences' in r.json()['detail']


def test_change_circularity_rejects_when_sequence_has_parents(sequences_client):
    c = sequences_client['client']
    pid = sequences_client['pcr_product_id']
    r = c.patch(
        f'/sequences/{pid}/change_circularity',
        headers=workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1']),
    )
    assert r.status_code == 400
    assert 'parent sequences' in r.json()['detail']


def test_change_circularity_rejects_when_sequence_has_overhangs(sequences_client):
    c = sequences_client['client']
    sid = sequences_client['seq_with_overhangs_id']
    r = c.patch(
        f'/sequences/{sid}/change_circularity',
        headers=workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1']),
    )
    assert r.status_code == 400
    assert 'overhangs' in r.json()['detail']


@pytest.mark.parametrize(
    'sid',
    [
        'seq_with_origin_spanning_feature_id',
        'seq_with_origin_spanning_feature_rc_id',
    ],
)
def test_change_circularity_rejects_when_sequence_has_features_spanning_origin(sequences_client, sid):
    c = sequences_client['client']
    sid = sequences_client[sid]
    r = c.patch(
        f'/sequences/{sid}/change_circularity',
        headers=workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1']),
    )
    assert r.status_code == 400
    assert 'features spanning the origin' in r.json()['detail']


def test_change_circularity_viewer_forbidden(sequences_client):
    c = sequences_client['client']
    tok = sequences_client['token_viewer_w1']
    r = c.patch(
        f"/sequences/{sequences_client['seq_w1_id']}/change_circularity",
        headers=workspace_headers(tok, sequences_client['w1']),
    )
    assert r.status_code == 403
    assert 'Not allowed' in r.json()['detail']


def test_change_circularity_workspace_mismatch_404(sequences_client):
    c = sequences_client['client']
    r = c.patch(
        f"/sequences/{sequences_client['seq_w2_id']}/change_circularity",
        headers=workspace_headers(
            sequences_client['token_owner_both'],
            sequences_client['w1'],
        ),
    )
    assert r.status_code == 404
    assert r.json()['detail'] == 'Sequence not found'


def test_change_circularity_unauthenticated_401(sequences_client):
    c = sequences_client['client']
    assert_patch_unauthenticated_401(
        c,
        f"/sequences/{sequences_client['seq_w1_id']}/change_circularity",
        sequences_client['w1'],
        json={},
    )


existing_sequence_annotated = Dseqrecord('aTgCag')
existing_sequence_annotated.add_feature(0, 4, type_='CDS')
existing_sequence_annotated = TextFileSequence.from_dseqrecord(existing_sequence_annotated).model_dump(mode='json')


def test_change_annotation_success_replaces_file(sequences_client):
    c = sequences_client['client']
    sid = sequences_client['seq_patch_linear_id']
    token = sequences_client['token_owner_w1']
    workspace_id = sequences_client['w1']
    headers = workspace_headers(token, workspace_id)
    base = Path(get_config().sequence_files_dir)

    with Session(sequences_client['engine']) as session:
        seq = session.get(Sequence, sid)
        old_relative = seq.file_path
    old_path = base / old_relative
    assert old_path.exists()

    r = c.patch(f'/sequences/{sid}/change_annotation', headers=headers, json=existing_sequence_annotated)
    assert r.status_code == 200

    r1 = c.get(f'/sequences/{sid}/text_file_sequence', headers=headers)
    assert r1.status_code == 200
    assert len(_parse_dseqr(r1.json()).features) == 1

    with Session(sequences_client['engine']) as session:
        seq = session.get(Sequence, sid)
        assert seq.file_path != old_relative
        new_path = base / seq.file_path

    assert not old_path.exists()
    assert new_path.exists()


def test_change_annotation_rejects_when_dseq_differs(sequences_client):
    c = sequences_client['client']
    sid = sequences_client['seq_patch_linear_id']
    payload = TextFileSequence.from_dseqrecord(Dseqrecord('TTTTTT', name='different')).model_dump(mode='json')
    r = c.patch(
        f'/sequences/{sid}/change_annotation',
        headers=workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1']),
        json=payload,
    )
    assert r.status_code == 400
    assert 'does not match the existing sequence' in r.json()['detail']


def test_change_annotation_viewer_forbidden(sequences_client):
    c = sequences_client['client']
    sid = sequences_client['seq_patch_linear_id']
    r = c.patch(
        f'/sequences/{sid}/change_annotation',
        headers=workspace_headers(sequences_client['token_viewer_w1'], sequences_client['w1']),
        json=existing_sequence_annotated,
    )
    assert r.status_code == 403
    assert 'Not allowed' in r.json()['detail']


def test_change_annotation_workspace_mismatch_404(sequences_client):
    c = sequences_client['client']
    sid = sequences_client['seq_w2_id']
    r = c.patch(
        f'/sequences/{sid}/change_annotation',
        headers=workspace_headers(sequences_client['token_owner_both'], sequences_client['w1']),
        json=existing_sequence_annotated,
    )
    assert r.status_code == 404
    assert r.json()['detail'] == 'Sequence not found'


def test_change_annotation_unauthenticated_401(sequences_client):
    c = sequences_client['client']
    sid = sequences_client['seq_patch_linear_id']
    assert_patch_unauthenticated_401(
        c,
        f'/sequences/{sid}/change_annotation',
        sequences_client['w1'],
        json=existing_sequence_annotated,
    )


def test_get_sequence_by_uid_scoped_to_workspace(sequences_client):
    """Resolve sequence by lab sample UID within the selected workspace."""
    c = sequences_client['client']
    tok = sequences_client['token_owner_w1']
    response = c.get(
        f"/sequences/by-uid/{sequences_client['uid_w1']}", headers=workspace_headers(tok, sequences_client['w1'])
    )
    assert response.status_code == 200
    assert response.json()['id'] == sequences_client['seq_w1_id']


def test_get_sequence_by_uid_not_found_404(sequences_client):
    c = sequences_client['client']
    r = c.get(
        '/sequences/by-uid/no-such-uid-xyz',
        headers=workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1']),
    )
    assert r.status_code == 404
    assert r.json()['detail'] == 'Sequence not found for UID'


def test_get_sequence_by_uid_forbidden_non_member(sequences_client):
    """Non-member cannot use by-uid with another workspace header."""
    c = sequences_client['client']
    tok = sequences_client['token_owner_w2']
    response = c.get(
        f"/sequences/by-uid/{sequences_client['uid_w1']}", headers=workspace_headers(tok, sequences_client['w1'])
    )
    assert response.status_code == 403
    assert 'Not allowed' in response.json()['detail']


def test_get_sequences_by_seguid_known(sequences_client):
    c = sequences_client['client']
    r = c.get(
        f"/sequences/by-seguid/{sequences_client['pcr_product_seguid']}",
        headers=workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1']),
    )
    assert r.status_code == 200
    ids = {item['id'] for item in r.json()}
    assert sequences_client['pcr_product_id'] in ids


def test_get_sequences_by_seguid_unknown_empty(sequences_client):
    c = sequences_client['client']
    r = c.get(
        '/sequences/by-seguid/zzzznonexistentseguiddummy',
        headers=workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1']),
    )
    assert r.status_code == 200
    assert r.json() == []


def _post_validate_upload_sequences(client, token: str, workspace_id: int, files: list[tuple[str, bytes]]):
    return client.post(
        '/sequences/validate-upload',
        headers=workspace_headers(token, workspace_id),
        files=[('files', (filename, body, 'application/octet-stream')) for filename, body in files],
    )


def _post_sequences_bulk(
    client,
    token: str,
    workspace_id: int,
    files: list[tuple[str, bytes]],
    strict: bool = True,
):
    return client.post(
        '/sequences/bulk',
        headers=workspace_headers(token, workspace_id),
        params={'strict': str(strict).lower()},
        files=[('files', (filename, body, 'application/octet-stream')) for filename, body in files],
    )


def test_validate_upload_sequences_returns_flags(sequences_client):
    c = sequences_client['client']
    h_token = sequences_client['token_owner_w1']
    wid = sequences_client['w1']

    dup = Dseqrecord('ATGCATGC', name='dup_name')
    linear_same_as_existing_circular = Dseqrecord('atgcgatcgatac', name='lin_to_existing_circular')
    invalid_content = b'not a valid sequence format'
    files = [
        ('dup1.gb', dup.format('genbank').encode('utf-8')),
        ('dup2.gb', dup.format('genbank').encode('utf-8')),
        ('linear.gb', linear_same_as_existing_circular.format('genbank').encode('utf-8')),
        ('bad.gb', invalid_content),
    ]

    r = _post_validate_upload_sequences(c, h_token, wid, files)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 4

    assert rows[0]['file_name'] == 'dup1.gb'
    assert rows[0]['reading_error'] is False
    assert rows[0]['name'] == 'dup_name'
    assert rows[0]['length'] == len(dup)
    assert rows[0]['circular'] is False
    assert rows[0]['sequence_exists'] is False
    assert rows[0]['name_exists'] is False
    assert rows[0]['duplicated_name'] is True
    assert rows[0]['duplicated_seguid'] is True
    assert rows[0]['sequence_circularised_exists'] is False
    assert rows[0]['circularised_seguid'] == dup.looped().seq.seguid()

    assert rows[1]['duplicated_name'] is True
    assert rows[1]['duplicated_seguid'] is True
    assert rows[1]['circularised_seguid'] == dup.looped().seq.seguid()

    assert rows[2]['file_name'] == 'linear.gb'
    assert rows[2]['reading_error'] is False
    assert rows[2]['circular'] is False
    assert rows[2]['sequence_exists'] is False
    assert rows[2]['sequence_circularised_exists'] is True
    assert rows[2]['circularised_seguid'] is not None
    assert rows[2]['duplicated_name'] is False
    assert rows[2]['duplicated_seguid'] is False

    assert rows[3]['file_name'] == 'bad.gb'
    assert rows[3]['reading_error'] is True
    assert rows[3]['name'] is None
    assert rows[3]['length'] is None
    assert rows[3]['circular'] is None
    assert rows[3]['seguid'] is None
    assert rows[3]['circularised_seguid'] is None
    assert rows[3]['sequence_exists'] is None
    assert rows[3]['sequence_circularised_exists'] is None
    assert rows[3]['name_exists'] is None
    assert rows[3]['duplicated_seguid'] is None
    assert rows[3]['duplicated_name'] is None


def test_validate_upload_sequences_limit_100(sequences_client):
    c = sequences_client['client']
    h_token = sequences_client['token_owner_w1']
    wid = sequences_client['w1']
    rec = Dseqrecord('ATGCATGC', name='bulk')
    body = rec.format('genbank').encode('utf-8')
    files = [(f'seq_{i}.gb', body) for i in range(101)]
    r = _post_validate_upload_sequences(c, h_token, wid, files)
    assert r.status_code == 400
    assert 'maximum of 100' in r.json()['detail']


def test_validate_upload_sequences_viewer_ok(sequences_client):
    c = sequences_client['client']
    rec = Dseqrecord('ATGCATGC', name='viewer_file')
    r = _post_validate_upload_sequences(
        c,
        sequences_client['token_viewer_w1'],
        sequences_client['w1'],
        [('viewer.gb', rec.format('genbank').encode('utf-8'))],
    )
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_validate_upload_sequences_non_member_forbidden(sequences_client):
    c = sequences_client['client']
    rec = Dseqrecord('ATGCATGC', name='forbidden_file')
    r = _post_validate_upload_sequences(
        c,
        sequences_client['token_owner_w2'],
        sequences_client['w1'],
        [('forbidden.gb', rec.format('genbank').encode('utf-8'))],
    )
    assert r.status_code == 403
    assert 'Not allowed' in r.json()['detail']


def test_validate_upload_sequences_missing_workspace_header_422(sequences_client):
    c = sequences_client['client']
    rec = Dseqrecord('ATGCATGC', name='missing_header')
    r = c.post(
        '/sequences/validate-upload',
        headers=bearer_headers(sequences_client['token_owner_w1']),
        files={'files': ('missing.gb', rec.format('genbank').encode('utf-8'), 'application/octet-stream')},
    )
    assert r.status_code == 422


def test_post_sequences_bulk_success_strict_true(sequences_client):
    c = sequences_client['client']
    h_token = sequences_client['token_owner_w1']
    wid = sequences_client['w1']
    payload = [
        ('bulk_ok_1.gb', Dseqrecord('ATGCATGCAAA', name='bulk_ok_1').format('genbank').encode('utf-8')),
        ('bulk_ok_2.gb', Dseqrecord('GGGATGCATTT', name='bulk_ok_2').format('genbank').encode('utf-8')),
    ]
    r = _post_sequences_bulk(c, h_token, wid, payload, strict=True)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    assert rows[0]['id'] > 0
    assert rows[1]['id'] > 0
    assert rows[0]['name'] == 'bulk_ok_1'
    assert rows[1]['name'] == 'bulk_ok_2'

    list_r = c.get('/sequences', headers=workspace_headers(h_token, wid), params={'name': 'bulk_ok'})
    assert list_r.status_code == 200
    assert len(list_r.json()['items']) == 2


def test_post_sequences_bulk_strict_true_conflict_on_warning_and_is_atomic(sequences_client):
    c = sequences_client['client']
    h_token = sequences_client['token_owner_w1']
    wid = sequences_client['w1']
    payload = [
        ('dup_a.gb', Dseqrecord('ATGCATGC', name='dup_name').format('genbank').encode('utf-8')),
        ('dup_b.gb', Dseqrecord('ATGCATGC', name='dup_name').format('genbank').encode('utf-8')),
    ]
    r = _post_sequences_bulk(c, h_token, wid, payload, strict=True)
    assert r.status_code == 409
    rows = r.json()
    assert len(rows) == 2
    assert rows[0]['duplicated_name'] is True
    assert rows[0]['duplicated_seguid'] is True
    assert rows[1]['duplicated_name'] is True
    assert rows[1]['duplicated_seguid'] is True

    list_r = c.get('/sequences', headers=workspace_headers(h_token, wid), params={'name': 'dup_name'})
    assert list_r.status_code == 200
    assert len([item for item in list_r.json()['items'] if item['name'] == 'dup_name']) == 0


def test_post_sequences_bulk_non_strict_allows_warnings(sequences_client):
    c = sequences_client['client']
    h_token = sequences_client['token_owner_w1']
    wid = sequences_client['w1']
    payload = [
        ('dup_a.gb', Dseqrecord('ATGCATGC', name='dup_non_strict').format('genbank').encode('utf-8')),
        ('dup_b.gb', Dseqrecord('ATGCATGC', name='dup_non_strict').format('genbank').encode('utf-8')),
    ]
    r = _post_sequences_bulk(c, h_token, wid, payload, strict=False)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    assert rows[0]['name'] == 'dup_non_strict'
    assert rows[1]['name'] == 'dup_non_strict'


def test_post_sequences_bulk_non_strict_still_rejects_reading_errors_and_is_atomic(sequences_client):
    c = sequences_client['client']
    h_token = sequences_client['token_owner_w1']
    wid = sequences_client['w1']
    payload = [
        ('ok.gb', Dseqrecord('ATGCATGCGG', name='ok_should_not_persist').format('genbank').encode('utf-8')),
        ('bad.gb', b'not a parseable sequence file'),
    ]
    r = _post_sequences_bulk(c, h_token, wid, payload, strict=False)
    assert r.status_code == 409
    rows = r.json()
    assert len(rows) == 2
    assert rows[0]['reading_error'] is False
    assert rows[1]['reading_error'] is True

    list_r = c.get('/sequences', headers=workspace_headers(h_token, wid), params={'name': 'ok_should_not_persist'})
    assert list_r.status_code == 200
    assert len([item for item in list_r.json()['items'] if item['name'] == 'ok_should_not_persist']) == 0


def test_post_sequences_bulk_viewer_forbidden(sequences_client):
    c = sequences_client['client']
    r = _post_sequences_bulk(
        c,
        sequences_client['token_viewer_w1'],
        sequences_client['w1'],
        [('viewer_forbidden.gb', Dseqrecord('ATGCATGC', name='viewer_forbidden').format('genbank').encode('utf-8'))],
    )
    assert r.status_code == 403
    assert 'Not allowed' in r.json()['detail']


def test_post_sequences_bulk_non_member_forbidden(sequences_client):
    c = sequences_client['client']
    r = _post_sequences_bulk(
        c,
        sequences_client['token_owner_w2'],
        sequences_client['w1'],
        [('non_member_forbidden.gb', Dseqrecord('ATGCATGC', name='non_member').format('genbank').encode('utf-8'))],
    )
    assert r.status_code == 403
    assert 'Not allowed' in r.json()['detail']


def test_post_sequences_bulk_missing_workspace_header_422(sequences_client):
    c = sequences_client['client']
    rec = Dseqrecord('ATGCATGC', name='missing_ws')
    r = c.post(
        '/sequences/bulk',
        headers=bearer_headers(sequences_client['token_owner_w1']),
        files={'files': ('missing_ws.gb', rec.format('genbank').encode('utf-8'), 'application/octet-stream')},
    )
    assert r.status_code == 422


def test_get_text_file_sequence_ok(sequences_client):
    c = sequences_client['client']
    r = c.get(
        f"/sequences/{sequences_client['pcr_product_id']}/text_file_sequence",
        headers=workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1']),
    )
    assert r.status_code == 200
    assert 'LOCUS' in r.json()['file_content']


@pytest.mark.parametrize(
    'query_sequence, expected_shift, expected_reverse_complemented, result_count',
    [
        (pcr_product, 0, False, 1),
        (pcr_template, 0, False, 1),
        (pcr_product.reverse_complement(), 0, True, 1),
        (pcr_template.reverse_complement(), 0, True, 1),
        (pcr_template.shifted(4), 4, False, 1),
        (pcr_template.shifted(-4), len(pcr_template) - 4, False, 1),
        (pcr_template.shifted(4).reverse_complement(), 4, True, 1),
        (Dseqrecord('A'), None, None, 0),
        (Dseqrecord(Dseq.from_full_sequence_and_overhangs(str(pcr_product.seq), -2, 0)), None, None, 0),
        (Dseqrecord(Dseq.from_full_sequence_and_overhangs(str(pcr_product.seq), 0, 2)), None, None, 0),
    ],
)
def test_post_sequence_search_finds_linear_and_circular_rotation(
    sequences_client, query_sequence, expected_shift, expected_reverse_complemented, result_count
):
    c = sequences_client['client']
    headers = workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1'])
    linear_query = TextFileSequence.from_dseqrecord(query_sequence)
    linear_r = c.post('/sequences/search', headers=headers, json=linear_query.model_dump(mode='json'))
    assert linear_r.status_code == 200
    matches = linear_r.json()
    assert len(matches) == result_count
    if result_count > 0:
        match = matches[0]
        assert match['shift'] == expected_shift
        assert match['reverse_complemented'] == expected_reverse_complemented


def test_get_cloning_strategy_pcr_product(sequences_client):
    c = sequences_client['client']
    r = c.get(
        f"/sequences/{sequences_client['pcr_product_id']}/cloning_strategy",
        headers=workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1']),
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data['sequences']) == 2
    assert len(data['sources']) == 2
    assert len(data['primers']) == 2


def test_get_sequence_children_template_to_product(sequences_client):
    c = sequences_client['client']
    r = c.get(
        f"/sequences/{sequences_client['pcr_template_id']}/children",
        headers=workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1']),
    )
    assert r.status_code == 200
    ids = [item['id'] for item in r.json()]
    assert ids == [sequences_client['pcr_product_id']]


def test_get_sequence_lines_returns_lines_for_sequence(sequences_client):
    c = sequences_client['client']
    headers = workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1'])
    r = c.get(f"/sequences/{sequences_client['pcr_template_id']}/lines", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert body[0]['uid'] == 'line-for-seq-filter'
    assert {item['sequence']['id'] for item in body[0]['sequences_in_line']} == {sequences_client['pcr_template_id']}


def test_get_sequence_lines_non_member_forbidden(sequences_client):
    c = sequences_client['client']
    r = c.get(
        f"/sequences/{sequences_client['pcr_template_id']}/lines",
        headers=workspace_headers(sequences_client['token_owner_w2'], sequences_client['w1']),
    )
    assert r.status_code == 403
    assert 'Not allowed' in r.json()['detail']


def test_get_sequence_lines_workspace_mismatch_404(sequences_client):
    c = sequences_client['client']
    r = c.get(
        f"/sequences/{sequences_client['seq_w2_id']}/lines",
        headers=workspace_headers(sequences_client['token_owner_both'], sequences_client['w1']),
    )
    assert r.status_code == 404
    assert r.json()['detail'] == 'Sequence not found'


def test_get_sequence_primers_pcr_template_and_product(sequences_client):
    """Template sequence is PCR input (template-side primers); product sequence lists output-side primers."""
    c = sequences_client['client']
    h = workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1'])
    t_r = c.get(f"/sequences/{sequences_client['pcr_template_id']}/primers", headers=h)
    assert t_r.status_code == 200
    t_data = t_r.json()
    assert len(t_data['templates']) == 2
    assert t_data['products'] == []

    p_r = c.get(f"/sequences/{sequences_client['pcr_product_id']}/primers", headers=h)
    assert p_r.status_code == 200
    p_data = p_r.json()
    assert len(p_data['products']) == 2
    assert p_data['templates'] == []


def test_post_sequencing_files_owner_ok(sequences_client):
    """Owner can upload sequencing files; GET lists them."""
    c = sequences_client['client']
    tok = sequences_client['token_owner_w1']
    wid = sequences_client['w1']
    sid = sequences_client['seq_w1_id']
    up = post_sequencing_file_upload(c, sid, tok, wid, 'run.ab1', b'ABIFDATA')
    assert up.status_code == 200
    data = up.json()
    assert len(data) == 1
    assert data[0]['original_name'] == 'run.ab1'
    assert set(data[0]) == {'id', 'original_name'}

    listed = c.get(
        f"/sequences/{sid}/sequencing_files",
        headers=workspace_headers(tok, wid),
    )
    assert listed.status_code == 200
    listed_body = listed.json()
    assert len(listed_body) == 1
    assert listed_body == data


def test_post_sequencing_files_viewer_forbidden(sequences_client):
    """Viewer cannot upload sequencing files."""
    c = sequences_client['client']
    r = post_sequencing_file_upload(
        c,
        sequences_client['seq_w1_id'],
        sequences_client['token_viewer_w1'],
        sequences_client['w1'],
        'nope.ab1',
        b'x',
    )
    assert r.status_code == 403
    assert 'Not allowed' in r.json()['detail']


def test_post_sequencing_files_non_member_forbidden(sequences_client):
    """Non-member cannot upload to another workspace sequence."""
    c = sequences_client['client']
    r = post_sequencing_file_upload(
        c,
        sequences_client['seq_w1_id'],
        sequences_client['token_owner_w2'],
        sequences_client['w1'],
        'nope.ab1',
        b'x',
    )
    assert r.status_code == 403
    assert 'Not allowed' in r.json()['detail']


def test_post_sequencing_files_workspace_mismatch_404(sequences_client):
    """W2 sequence id with W1 header returns 404 on upload."""
    c = sequences_client['client']
    r = post_sequencing_file_upload(
        c,
        sequences_client['seq_w2_id'],
        sequences_client['token_owner_both'],
        sequences_client['w1'],
        'x.ab1',
        b'x',
    )
    assert r.status_code == 404
    assert r.json()['detail'] == 'Sequence not found'


def test_get_sequence_sequencing_files_viewer_ok(sequences_client):
    """Viewer can list sequencing files after owner uploads."""
    c = sequences_client['client']
    owner = sequences_client['token_owner_w1']
    viewer = sequences_client['token_viewer_w1']
    wid = sequences_client['w1']
    sid = sequences_client['seq_w1_id']
    up = post_sequencing_file_upload(
        c,
        sid,
        owner,
        wid,
        'viewer-list.ab1',
        b'AB1',
    )
    assert up.status_code == 200

    listed = c.get(
        f"/sequences/{sid}/sequencing_files",
        headers=workspace_headers(viewer, wid),
    )
    assert listed.status_code == 200
    assert listed.json() == up.json()


def test_get_sequence_sequencing_files_non_member_forbidden(sequences_client):
    """Non-member cannot list sequencing files for another workspace."""
    c = sequences_client['client']
    listed = c.get(
        f"/sequences/{sequences_client['seq_w1_id']}/sequencing_files",
        headers=workspace_headers(
            sequences_client['token_owner_w2'],
            sequences_client['w1'],
        ),
    )
    assert listed.status_code == 403
    assert 'Not allowed' in listed.json()['detail']


def test_delete_sequencing_file_owner_204(sequences_client):
    """Owner can delete a sequencing file (204)."""
    c = sequences_client['client']
    tok = sequences_client['token_owner_w1']
    wid = sequences_client['w1']
    sid = sequences_client['seq_w1_id']
    up = post_sequencing_file_upload(c, sid, tok, wid, 'del.ab1', b'DEL')
    assert up.status_code == 200
    file_id = up.json()[0]['id']

    r = c.delete(
        f"/sequences/{sid}/sequencing_files/{file_id}",
        headers=workspace_headers(tok, wid),
    )
    assert r.status_code == 204


def test_delete_sequencing_file_viewer_forbidden(sequences_client):
    """Viewer cannot delete sequencing files."""
    c = sequences_client['client']
    owner = sequences_client['token_owner_w1']
    viewer = sequences_client['token_viewer_w1']
    wid = sequences_client['w1']
    sid = sequences_client['seq_w1_id']
    up = post_sequencing_file_upload(c, sid, owner, wid, 'v-del.ab1', b'V')
    assert up.status_code == 200
    file_id = up.json()[0]['id']

    r = c.delete(
        f"/sequences/{sid}/sequencing_files/{file_id}",
        headers=workspace_headers(viewer, wid),
    )
    assert r.status_code == 403
    assert 'Not allowed' in r.json()['detail']


def test_delete_sequencing_file_wrong_sequence_404(sequences_client):
    """File belongs to W1 sequence; DELETE under W2 path returns 404."""
    c = sequences_client['client']
    tok_w1 = sequences_client['token_owner_w1']
    both = sequences_client['token_owner_both']
    w1 = sequences_client['w1']
    w2 = sequences_client['w2']
    sid1 = sequences_client['seq_w1_id']
    sid2 = sequences_client['seq_w2_id']
    up = post_sequencing_file_upload(c, sid1, tok_w1, w1, 'wrongseq.ab1', b'W')
    assert up.status_code == 200
    file_id = up.json()[0]['id']

    r = c.delete(
        f"/sequences/{sid2}/sequencing_files/{file_id}",
        headers=workspace_headers(both, w2),
    )
    assert r.status_code == 404
    assert r.json()['detail'] == 'Sequencing file not found'


def test_download_sequencing_file_ok(sequences_client):
    c = sequences_client['client']
    payload = b'DOWNLOAD-BYTES-123'
    up = post_sequencing_file_upload(
        c,
        sequences_client['seq_w1_id'],
        sequences_client['token_owner_w1'],
        sequences_client['w1'],
        'dl.ab1',
        payload,
    )
    assert up.status_code == 200
    file_id = up.json()[0]['id']
    r = c.get(
        f"/sequencing_files/{file_id}/download",
        headers=workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1']),
    )
    assert r.status_code == 200
    assert r.content == payload


def test_download_sequencing_file_ok_then_missing_on_disk_404(sequences_client):
    """Happy download, then blob removed from disk → 404 (same client/session as upload)."""
    c = sequences_client['client']
    tok = sequences_client['token_owner_w1']
    wid = sequences_client['w1']
    payload = b'ROUNDTRIP'
    up = post_sequencing_file_upload(
        c,
        sequences_client['seq_w1_id'],
        tok,
        wid,
        'round.ab1',
        payload,
    )
    assert up.status_code == 200
    file_id = up.json()[0]['id']
    ok = c.get(
        f"/sequencing_files/{file_id}/download",
        headers=workspace_headers(tok, wid),
    )
    assert ok.status_code == 200
    assert ok.content == payload

    with Session(sequences_client['engine']) as session:
        sf = session.get(SequencingFile, file_id)
        disk_path = Path(sequences_client['sequencing_files_dir']) / sf.storage_path
    disk_path.unlink()
    missing = c.get(
        f"/sequencing_files/{file_id}/download",
        headers=workspace_headers(tok, wid),
    )
    assert missing.status_code == 404
    assert missing.json()['detail'] == 'File not found on disk'


def test_download_sequencing_file_unknown_id_404(sequences_client):
    c = sequences_client['client']
    r = c.get(
        '/sequencing_files/999999999/download',
        headers=workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1']),
    )
    assert r.status_code == 404
    assert r.json()['detail'] == 'Sequencing file not found'


def test_download_sequencing_file_zz_forbidden_cross_workspace(sequences_client):
    """User without W1 access cannot download a file uploaded under W1.

    Previous note: Runs after other download tests: a 403 download in the same TestClient session
    can leave state that breaks a following successful download in some setups.
    """
    c = sequences_client['client']
    tok = sequences_client['token_owner_w2']
    uploaded = post_sequencing_file_upload(
        c,
        sequences_client['seq_w1_id'],
        sequences_client['token_owner_w1'],
        sequences_client['w1'],
        'test.ab1',
        b'ABIF',
    )
    assert uploaded.status_code == 200
    file_id = uploaded.json()[0]['id']

    download = c.get(
        f"/sequencing_files/{file_id}/download",
        headers=workspace_headers(tok, sequences_client['w1']),
    )
    assert download.status_code == 403
    assert 'Not allowed' in download.json()['detail']


def test_get_sequences_invalid_workspace_id_header_422(sequences_client):
    """Non-integer X-Workspace-Id on GET /sequences yields 422."""
    assert_get_invalid_workspace_id_422(
        sequences_client['client'],
        '/sequences',
        sequences_client['token_owner_w1'],
        invalid='bad',
    )


def test_get_sequences_non_member_workspace_w3_forbidden_403(sequences_client):
    """Member of W1 only cannot use workspace W3 header."""
    assert_get_non_member_workspace_403(
        sequences_client['client'],
        '/sequences',
        sequences_client['token_owner_w1'],
        sequences_client['w3'],
    )


def test_get_sequences_unauthenticated_401(sequences_client):
    """GET /sequences without Authorization is rejected."""
    assert_get_unauthenticated_401(
        sequences_client['client'],
        '/sequences',
        sequences_client['w1'],
    )


def test_download_sequencing_file_no_workspace_header_422(sequences_client):
    """Sequencing download requires X-Workspace-Id (422 if missing)."""
    c = sequences_client['client']
    uploaded = post_sequencing_file_upload(
        c,
        sequences_client['seq_w1_id'],
        sequences_client['token_owner_w1'],
        sequences_client['w1'],
        'f.ab1',
        b'ABIF',
    )
    assert uploaded.status_code == 200
    file_id = uploaded.json()[0]['id']

    tok_w1 = sequences_client['token_owner_w1']
    download = c.get(
        f"/sequencing_files/{file_id}/download",
        headers=bearer_headers(tok_w1),
    )
    assert download.status_code == 422
    assert download.json()['detail']


def test_download_sequencing_file_wrong_workspace_404(sequences_client):
    """W1 file id with W2 header: 404 (sequence not in selected workspace)."""
    c = sequences_client['client']
    uploaded = post_sequencing_file_upload(
        c,
        sequences_client['seq_w1_id'],
        sequences_client['token_owner_w1'],
        sequences_client['w1'],
        'w.ab1',
        b'ABIF',
    )
    assert uploaded.status_code == 200
    file_id = uploaded.json()[0]['id']

    download = c.get(
        f"/sequencing_files/{file_id}/download",
        headers=workspace_headers(
            sequences_client['token_owner_both'],
            sequences_client['w2'],
        ),
    )
    assert download.status_code == 404
    assert download.json()['detail'] == 'Sequence not found'


def test_patch_sequence_cross_workspace_header_404(sequences_client):
    """PATCH W2 sequence id with W1 header returns 404."""
    c = sequences_client['client']
    tok = sequences_client['token_owner_both']
    response = c.patch(
        f"/sequences/{sequences_client['seq_w2_id']}",
        headers=workspace_headers(tok, sequences_client['w1']),
        json={'name': 'should-not-apply'},
    )
    assert response.status_code == 404
    assert response.json()['detail'] == 'Sequence not found'


def test_post_cloning_strategy_from_example(sequences_client):
    c = sequences_client['client']
    body = opencloning_models.CloningStrategy.model_validate(cs_pcr.model_dump(mode='json')).model_dump(mode='json')
    r = c.post(
        '/sequences',
        headers=workspace_headers(
            sequences_client['token_owner_w1'],
            sequences_client['w1'],
            extra={'Content-Type': 'application/json'},
        ),
        json=body,
    )
    assert r.status_code == 200
    out = r.json()
    assert 'id' in out
    assert isinstance(out['mappings'], list)


def test_search_rotation_errors():
    with pytest.raises(ValueError):
        _search_rotation(Dseq('ATGC'), Dseq('ATG'))
    with pytest.raises(ValueError):
        _search_rotation(Dseq('ATGC'), Dseq('ATGC', circular=True))
    with pytest.raises(ValueError):
        _search_rotation(Dseq('ATGC', circular=True), Dseq('ATGC'))
    with pytest.raises(ValueError):
        _search_rotation(Dseq('ATGCA', circular=True), Dseq('ATGC', circular=True))
    with pytest.raises(ValueError):
        _search_rotation(Dseq('ATGCT', circular=True), Dseq('ATGCA', circular=True))


def test_post_cloning_strategy_sets_created_by(sequences_client):
    """Sequences (and any primers) created from a cloning strategy carry the creator."""
    c = sequences_client['client']
    headers = workspace_headers(
        sequences_client['token_owner_w1'],
        sequences_client['w1'],
        extra={'Content-Type': 'application/json'},
    )
    body = opencloning_models.CloningStrategy.model_validate(cs_pcr.model_dump(mode='json')).model_dump(mode='json')
    r = c.post('/sequences', headers=headers, json=body)
    assert r.status_code == 200, r.text
    root_id = r.json()['id']

    list_headers = workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1'])
    r2 = c.get(f"/sequences/{root_id}", headers=list_headers)
    assert r2.status_code == 200
    seq_body = r2.json()
    assert seq_body['created_by'] == {
        'id': sequences_client['owner_w1_id'],
        'display_name': 'Owner W1',
    }
    assert seq_body['created_at'] is not None


def test_get_sequence_returns_created_at_and_created_by_for_seeded(sequences_client):
    """Seeded sequences (no creator) still expose created_at and a null created_by."""
    c = sequences_client['client']
    headers = workspace_headers(sequences_client['token_owner_w1'], sequences_client['w1'])
    r = c.get(f"/sequences/{sequences_client['seq_w1_id']}", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body['created_at'] is not None
    assert body['created_by'] == {'display_name': 'Owner W1', 'id': 1}


def test_get_sequences_filter_by_created_by(sequences_client):
    """GET /sequences?created_by=... filters by creator display_name substring."""
    c = sequences_client['client']
    wid = sequences_client['w1']
    headers_owner = workspace_headers(
        sequences_client['token_owner_w1'],
        wid,
        extra={'Content-Type': 'application/json'},
    )
    headers_both = workspace_headers(
        sequences_client['token_owner_both'],
        wid,
        extra={'Content-Type': 'application/json'},
    )

    body_owner = opencloning_models.CloningStrategy.model_validate(cs_pcr.model_dump(mode='json')).model_dump(
        mode='json'
    )
    r = c.post('/sequences', headers=headers_owner, json=body_owner)
    assert r.status_code == 200, r.text
    owner_root_id = r.json()['id']

    body_both = opencloning_models.CloningStrategy.model_validate(cs_gateway_BP.model_dump(mode='json')).model_dump(
        mode='json'
    )
    r = c.post('/sequences', headers=headers_both, json=body_both)
    assert r.status_code == 200, r.text
    both_root_id = r.json()['id']

    list_headers = workspace_headers(sequences_client['token_owner_w1'], wid)
    r = c.get('/sequences?created_by=Owner W1', headers=list_headers)
    assert r.status_code == 200
    owner_w1_ids = {it['id'] for it in r.json()['items']}
    assert owner_root_id in owner_w1_ids
    assert both_root_id not in owner_w1_ids

    r = c.get('/sequences?created_by=owner', headers=list_headers)
    assert r.status_code == 200
    owner_ids = {it['id'] for it in r.json()['items']}
    assert owner_root_id in owner_ids
    assert both_root_id in owner_ids

    r = c.get('/sequences?created_by=nobody', headers=list_headers)
    assert r.status_code == 200
    assert r.json()['items'] == []


def test_post_sequences_bulk_sets_created_by(sequences_client):
    """Bulk-uploaded sequences are attributed to the requesting user."""
    c = sequences_client['client']
    wid = sequences_client['w1']
    headers_owner = workspace_headers(sequences_client['token_owner_w1'], wid)

    seq_record = Dseqrecord('atgcacgtagctagctagctagctgactgactg', name='bulk-attributed')
    file_content = seq_record.format('genbank')
    files = {'files': ('bulk_attr.gb', file_content, 'application/octet-stream')}
    r = c.post('/sequences/bulk', headers=headers_owner, files=files)
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) == 1
    assert items[0]['created_by'] == {
        'id': sequences_client['owner_w1_id'],
        'display_name': 'Owner W1',
    }
    assert items[0]['created_at'] is not None
