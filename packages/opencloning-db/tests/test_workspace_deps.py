"""Lightweight tests around workspace_deps helpers.

Most behavior is already covered by the primers/lines router tests; here we
only exercise the highest-value pieces directly (404 vs 403 behavior).
"""

import pytest
from fastapi import HTTPException
from opencloning_db.workspace_scope import UnscopedSession

from opencloning_db.models import InputEntity, Line, Primer, Sequence, SequenceType, Tag, User, WorkspaceRole
from opencloning_db.workspace_deps import (
    get_line_in_workspace_for_user,
    get_resource_in_workspace_for_user,
    get_sequence_in_workspace_for_user,
    get_sequence_sample_in_workspace_for_user,
)
from .helpers import seed_standard_users

readonly_db = pytest.mark.readonly_db


@pytest.fixture
def deps_session(request):
    """Small fixture to exercise workspace_deps access checks."""
    fixture_name = (
        'engine_client_config_readonly'
        if request.node.get_closest_marker('readonly_db')
        else 'engine_client_config_write'
    )
    engine, _, _ = request.getfixturevalue(fixture_name)

    with UnscopedSession(engine) as session:
        ctx = seed_standard_users(session)

        line = Line(workspace_id=ctx['w1'], uid='DEPS-LINE', created_by_id=ctx['owner_w1_id'])
        seq = Sequence(
            workspace_id=ctx['w1'],
            name='deps-seq',
            file_content='deps.gb',
            sequence_type=SequenceType.allele,
            seguid='SEGUID-DEPS-SEQ',
            created_by_id=ctx['owner_w1_id'],
        )
        session.add_all([line, seq])
        session.commit()
        return {
            'engine': engine,
            'user_id': ctx['owner_w1_id'],
            'other_user_id': ctx['owner_w2_id'],
            'workspace_id': ctx['w1'],
            'other_workspace_id': ctx['w2'],
            'line_id': line.id,
            'sequence_id': seq.id,
        }


def test_get_line_in_workspace_enforces_membership(deps_session):
    """A member loads the line; a non-member of the selected workspace gets 403; a foreign line is 404."""

    with UnscopedSession(deps_session['engine']) as session:

        user = session.get(User, deps_session['user_id'])
        other_user = session.get(User, deps_session['other_user_id'])
        line_id = deps_session['line_id']

        line = get_line_in_workspace_for_user(
            session, user, deps_session['workspace_id'], line_id, WorkspaceRole.viewer
        )
        assert line.id == line_id

        # Selecting a workspace the user is not a member of -> 403, whatever the id
        for resource_id in (line_id, 999_999):
            with pytest.raises(HTTPException) as exc:
                get_line_in_workspace_for_user(
                    session, other_user, deps_session['workspace_id'], resource_id, WorkspaceRole.viewer
                )
            assert exc.value.status_code == 403
            assert 'Not allowed' in exc.value.detail

        # From the user's own workspace, the line of another workspace is the same 404 as a missing one
        for resource_id in (line_id, 999_999):
            with pytest.raises(HTTPException) as exc:
                get_line_in_workspace_for_user(
                    session, other_user, deps_session['other_workspace_id'], resource_id, WorkspaceRole.viewer
                )
            assert exc.value.status_code == 404
            assert exc.value.detail == 'Line not found'


def test_get_sequence_in_workspace_for_user_checks_workspace_and_type(
    deps_session,
):
    """Resolve sequence when workspace and type match; else 404/400."""
    with UnscopedSession(deps_session['engine']) as session:
        user = session.get(User, deps_session['user_id'])

        seq = get_sequence_in_workspace_for_user(
            session,
            user,
            deps_session['workspace_id'],
            deps_session['sequence_id'],
            WorkspaceRole.viewer,
            expected_type=SequenceType.allele,
        )
        assert seq.id == deps_session['sequence_id']

        # Sequence of another workspace, requested by a member of the selected workspace -> 404
        other_user = session.get(User, deps_session['other_user_id'])
        with pytest.raises(HTTPException) as exc:
            get_sequence_in_workspace_for_user(
                session,
                other_user,
                deps_session['other_workspace_id'],
                deps_session['sequence_id'],
                WorkspaceRole.viewer,
                expected_type=SequenceType.allele,
            )
        assert exc.value.status_code == 404
        assert exc.value.detail == 'BaseSequence not found'

        # Wrong type -> 400
        with pytest.raises(HTTPException) as exc2:
            get_sequence_in_workspace_for_user(
                session,
                user,
                deps_session['workspace_id'],
                deps_session['sequence_id'],
                WorkspaceRole.viewer,
                expected_type=SequenceType.plasmid,
            )
        assert exc2.value.status_code == 400
        assert 'not of type' in exc2.value.detail


def test_get_resource_in_workspace_missing_entity_404(deps_session):
    """All get_*_in_workspace_for_user helpers return 404 with resource-specific detail."""

    with UnscopedSession(deps_session['engine']) as session:
        user = session.get(User, deps_session['user_id'])
        for resource_type in [Line, Sequence, Primer, Tag, InputEntity]:
            with pytest.raises(HTTPException) as exc:
                get_resource_in_workspace_for_user(
                    session, user, deps_session['workspace_id'], 999_999, WorkspaceRole.viewer, resource_type
                )
            assert exc.value.status_code == 404
            assert exc.value.detail == f"{resource_type.__name__} not found"


def test_get_sequence_in_workspace_missing_id_404(deps_session):
    """Missing sequence id returns 404."""
    with UnscopedSession(deps_session['engine']) as session:
        user = session.get(User, deps_session['user_id'])
        with pytest.raises(HTTPException) as exc:
            get_sequence_in_workspace_for_user(
                session,
                user,
                deps_session['workspace_id'],
                999_999,
                WorkspaceRole.viewer,
                expected_type=SequenceType.allele,
            )
        assert exc.value.status_code == 404
        assert exc.value.detail == 'BaseSequence not found'


def test_get_sequence_sample_in_workspace_for_user_missing_404(deps_session):
    """Unknown sample uid returns 404."""
    with UnscopedSession(deps_session['engine']) as session:
        user = session.get(User, deps_session['user_id'])
        with pytest.raises(HTTPException) as exc:
            get_sequence_sample_in_workspace_for_user(
                session,
                user,
                deps_session['workspace_id'],
                'MISSING-SAMPLE-UID',
                WorkspaceRole.viewer,
            )
        assert exc.value.status_code == 404
        assert exc.value.detail == 'Sequence sample not found'
