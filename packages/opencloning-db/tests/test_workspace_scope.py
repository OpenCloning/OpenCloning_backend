"""Automatic workspace scoping of ORM queries and writes (opencloning_db.workspace_scope)."""

from contextlib import contextmanager

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from opencloning_db.context import WriteContext
from opencloning_db.db import cloning_strategy_to_db, create_sequencing_file
from opencloning_db.models import (
    Base,
    BaseSequence,
    InputEntity,
    Line,
    Primer,
    Sequence,
    SequenceInLine,
    SequenceSample,
    SequencingFile,
    Source,
    SourceInput,
    Tag,
    User,
    input_entity_tag,
)
from opencloning_db.workspace_scope import (
    DIRECT_WORKSPACE_MODELS,
    GLOBAL_MODELS,
    INDIRECT_WORKSPACE_MODELS,
    WorkspaceScopeError,
    bind_workspace,
    require_workspace_scope,
)
from tests.cloning_strategy_examples import cs_pcr
from .helpers import attach_standard_tokens, seed_standard_users, workspace_headers

readonly_db = pytest.mark.readonly_db

MISSING_ID = 10**9


def _seed_workspace(session: Session, workspace_id: int, user_id: int, suffix: str) -> dict[str, int]:
    """One row of every workspace-scoped model in the workspace; returns ids by model name."""
    ctx = WriteContext(user=User(id=user_id, email='unused@test'), workspace_id=workspace_id)
    sequences, _ = cloning_strategy_to_db(cs_pcr, session, ctx=ctx)
    product = next(s for s in sequences if s.output_of_source.input)
    template = next(s for s in sequences if not s.output_of_source.input)
    primer = session.scalars(select(Primer).where(Primer.workspace_id == workspace_id)).first()

    tag = Tag(name=f'tag-{suffix}', workspace_id=workspace_id)
    product.tags.append(tag)
    line = Line.from_create(uid=f'line-{suffix}', ctx=ctx)
    sequence_in_line = SequenceInLine(sequence=template, line=line, workspace_id=workspace_id)
    sample = SequenceSample(uid=f'uid-{suffix}', sequence_id=product.id, workspace_id=workspace_id)
    sequencing_file = create_sequencing_file(product, b'ABIF', f'{suffix}.ab1')
    session.add_all([tag, line, sequence_in_line, sample, sequencing_file])
    session.flush()
    return {
        'InputEntity': primer.id,
        'Primer': primer.id,
        'BaseSequence': product.id,
        'Sequence': product.id,
        'Source': product.id,
        'Tag': tag.id,
        'Line': line.id,
        'SequenceInLine': sequence_in_line.id,
        'SequenceSample': sample.id,
        'SequencingFile': sequencing_file.id,
    }


def _seed(engine, client) -> dict:
    with Session(engine) as session:
        ctx = seed_standard_users(session)
        ctx['ids'] = {
            ctx['w1']: _seed_workspace(session, ctx['w1'], ctx['owner_w1_id'], 'w1'),
            ctx['w2']: _seed_workspace(session, ctx['w2'], ctx['owner_w2_id'], 'w2'),
        }
        session.commit()
    ctx['engine'] = engine
    return attach_standard_tokens(ctx, client)


@pytest.fixture(scope='module')
def _scope_db_readonly(engine_client_config_readonly):
    engine, client, _ = engine_client_config_readonly
    return _seed(engine, client)


@pytest.fixture
def scope_db(request):
    if request.node.get_closest_marker('readonly_db'):
        return request.getfixturevalue('_scope_db_readonly')
    engine, client, _ = request.getfixturevalue('engine_client_config_write')
    return _seed(engine, client)


@contextmanager
def _bound_session(engine, workspace_id: int):
    """A session set up like an API request inside a workspace context."""
    with Session(engine) as session:
        require_workspace_scope(session)
        bind_workspace(session, workspace_id)
        yield session


def test_every_model_is_classified():
    """A new model must be declared global or get a workspace criterion."""
    roots = GLOBAL_MODELS + DIRECT_WORKSPACE_MODELS + INDIRECT_WORKSPACE_MODELS
    unclassified = [mapper.class_.__name__ for mapper in Base.registry.mappers if not issubclass(mapper.class_, roots)]
    assert unclassified == []


SCOPED_MODELS = [
    InputEntity,
    BaseSequence,
    Sequence,
    Primer,
    Tag,
    Line,
    SequenceInLine,
    SequenceSample,
    SequencingFile,
]


@readonly_db
@pytest.mark.parametrize('model', [*SCOPED_MODELS, Source], ids=lambda m: m.__name__)
def test_bound_session_hides_other_workspace(scope_db, model):
    # For each model type, get the id of the row created in each workspace
    own_id = scope_db['ids'][scope_db['w1']][model.__name__]
    foreign_id = scope_db['ids'][scope_db['w2']][model.__name__]
    with _bound_session(scope_db['engine'], scope_db['w1']) as session:
        # Requesting rows by id
        assert session.get(model, own_id) is not None
        assert session.get(model, foreign_id) is None
        # Request all rows for that model type
        ids = set(session.scalars(select(model.id)))
        assert own_id in ids
        assert foreign_id not in ids
        # Select query
        assert session.query(model).filter_by(id=foreign_id).first() is None
        # Inside a subquery
        assert (
            session.scalar(select(func.count()).select_from(select(model).where(model.id == foreign_id).subquery()))
            == 0
        )


def _inputs_of(session: Session, source_id: int) -> list[SourceInput]:
    return session.scalars(select(SourceInput).where(SourceInput.source_id == source_id)).all()


@readonly_db
def test_bound_session_hides_other_workspace_source_inputs(scope_db):
    own_source_id = scope_db['ids'][scope_db['w1']]['Source']
    foreign_source_id = scope_db['ids'][scope_db['w2']]['Source']
    with Session(scope_db['engine']) as session:
        # The foreign source has inputs, so an empty result below means hidden, not missing
        assert _inputs_of(session, foreign_source_id) != []
    with _bound_session(scope_db['engine'], scope_db['w1']) as session:
        assert _inputs_of(session, own_source_id) != []
        assert _inputs_of(session, foreign_source_id) == []


def test_bound_session_filters_relationship_loads(scope_db):
    """Even a link that crosses workspaces (e.g. legacy data) does not expose the other workspace."""
    w1, w2 = scope_db['w1'], scope_db['w2']
    own_tag_id = scope_db['ids'][w1]['Tag']
    foreign_primer_id = scope_db['ids'][w2]['Primer']
    with Session(scope_db['engine']) as session:
        session.execute(input_entity_tag.insert().values(input_entity_id=foreign_primer_id, tag_id=own_tag_id))
        session.commit()

    # The tag in workspace 1 does not show the primer in workspace 2
    with _bound_session(scope_db['engine'], w1) as session:
        tag = session.get(Tag, own_tag_id)
        lazy_ids = {entity.id for entity in tag.input_entities}
        assert foreign_primer_id not in lazy_ids
        assert scope_db['ids'][w1]['Sequence'] in lazy_ids
    with _bound_session(scope_db['engine'], w1) as session:
        tag = session.scalars(select(Tag).where(Tag.id == own_tag_id).options(selectinload(Tag.input_entities))).one()
        assert foreign_primer_id not in {entity.id for entity in tag.input_entities}

    # The primer in workspace 2 does not show the tag in workspace 1
    with _bound_session(scope_db['engine'], w2) as session:
        assert session.get(Primer, foreign_primer_id).tags == []


@readonly_db
def test_alternating_workspaces_use_the_right_workspace(scope_db):
    """The statement cache must never reuse the workspace id of a previous session."""
    w1, w2 = scope_db['w1'], scope_db['w2']
    with Session(scope_db['engine']) as session:
        expected_primers = {
            w: set(session.scalars(select(Primer.id).where(Primer.workspace_id == w))) for w in (w1, w2)
        }
    for _ in range(3):
        for w in (w1, w2):
            with _bound_session(scope_db['engine'], w) as session:
                # For entities with workspace_id
                assert set(session.scalars(select(Primer.id))) == expected_primers[w]
                # For linked rows (models without workspace_id)
                assert set(session.scalars(select(SequencingFile.id))) == {scope_db['ids'][w]['SequencingFile']}


@readonly_db
def test_unbound_request_session_only_allows_global_models(scope_db):
    with Session(scope_db['engine']) as session:
        require_workspace_scope(session)
        assert session.get(User, scope_db['owner_w1_id']) is not None
        with pytest.raises(WorkspaceScopeError):
            session.scalars(select(Primer)).all()
        with pytest.raises(WorkspaceScopeError):
            session.get(Tag, scope_db['ids'][scope_db['w1']]['Tag'])
        # Workspace rows reached through select_from or a join are hidden instead
        assert session.scalar(select(func.count()).select_from(InputEntity)) == 0
        assert session.scalars(select(User).join(InputEntity, InputEntity.created_by_id == User.id)).all() == []


@readonly_db
def test_unscoped_session_is_not_affected(scope_db):
    """Sessions created outside requests (CLI, seeding, tests) see everything."""
    with Session(scope_db['engine']) as session:
        ids = set(session.scalars(select(Tag.id)))
        assert {scope_db['ids'][scope_db['w1']]['Tag'], scope_db['ids'][scope_db['w2']]['Tag']} <= ids


@pytest.mark.parametrize('model', [Primer, SequenceSample], ids=lambda m: m.__name__)
def test_database_rejects_inconsistent_workspace_copy(scope_db, model):
    """The workspace copy next to the uid cannot disagree with the real workspace, even through raw SQL."""
    table = model.__table__
    row_id = scope_db['ids'][scope_db['w1']][model.__name__]
    with Session(scope_db['engine']) as session:
        with pytest.raises(IntegrityError):
            session.execute(update(table).where(table.c.id == row_id).values(workspace_id=scope_db['w2']))


def test_write_guard_rejects_rows_of_other_workspace(scope_db):
    w1, w2 = scope_db['w1'], scope_db['w2']
    with _bound_session(scope_db['engine'], w1) as session:
        session.add(Tag(name='elsewhere', workspace_id=w2))
        with pytest.raises(WorkspaceScopeError):
            session.flush()
    with _bound_session(scope_db['engine'], w1) as session:
        tag = session.get(Tag, scope_db['ids'][w1]['Tag'])
        tag.workspace_id = w2
        with pytest.raises(WorkspaceScopeError):
            session.flush()


@readonly_db
def test_bind_workspace_cannot_switch_workspace(scope_db):
    with _bound_session(scope_db['engine'], scope_db['w1']) as session:
        bind_workspace(session, scope_db['w1'])
        with pytest.raises(WorkspaceScopeError):
            bind_workspace(session, scope_db['w2'])


@readonly_db
@pytest.mark.parametrize(
    'path, model',
    [
        ('/primers/{}', 'Primer'),
        ('/sequences/{}', 'Sequence'),
        ('/lines/{}', 'Line'),
        ('/sequencing_files/{}/download', 'SequencingFile'),
    ],
)
def test_api_foreign_id_same_as_missing(scope_db, path, model):
    """A user without access to W2 cannot tell W2 ids from ids that do not exist."""
    client = scope_db['client']
    headers = workspace_headers(scope_db['token_owner_w1'], scope_db['w1'])
    foreign = client.get(path.format(scope_db['ids'][scope_db['w2']][model]), headers=headers)
    missing = client.get(path.format(MISSING_ID), headers=headers)
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


def test_api_foreign_tag_same_as_missing(scope_db):
    client = scope_db['client']
    headers = workspace_headers(scope_db['token_owner_w1'], scope_db['w1'])
    own_primer_id = scope_db['ids'][scope_db['w1']]['Primer']
    responses = [
        client.post(f'/input_entities/{own_primer_id}/tags', headers=headers, json={'tag_id': tag_id})
        for tag_id in (scope_db['ids'][scope_db['w2']]['Tag'], MISSING_ID)
    ]
    assert [r.status_code for r in responses] == [404, 404]
    assert responses[0].json() == responses[1].json() == {'detail': 'Tag not found'}
