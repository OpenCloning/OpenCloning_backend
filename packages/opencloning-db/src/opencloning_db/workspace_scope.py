"""
Automatic workspace scoping for ORM queries.

Every session is scoped unless it is an ``UnscopedSession``. A scoped session (``RequestSession``, or a plain
``Session``) starts unbound and may only query global models (users, workspaces, memberships). Once bound to a
workspace (``bind_workspace``, called by the workspace context dependencies), every ORM SELECT on workspace data
is filtered to that workspace, however it is written: ``session.get``, ``select``, legacy ``query()``,
relationship loads and subqueries. Rows of other workspaces behave as if they did not exist, and writing them is
refused at flush.

A session can also be bound read-only (viewer routes). Then every write is refused: in the ORM at flush, and by
Postgres for any statement (``SET TRANSACTION READ ONLY``, re-applied to each new transaction).

``UnscopedSession`` is the explicit opt-out that sees all workspaces. Only tests use it; application code must not
(enforced by the ``unscoped-session-check`` pre-commit hook).

Limits: core table queries (``select(table.c...)``) and raw SQL are not filtered by the scoping.
"""

from sqlalchemy import event, exists
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from opencloning_db.models import (
    Base,
    InputEntity,
    Line,
    SequenceInstance,
    SequencingFile,
    Source,
    SourceInput,
    Tag,
    User,
    Workspace,
    WorkspaceMembership,
)

_WORKSPACE_ID_KEY = 'opencloning_workspace_id'
_READ_ONLY_KEY = 'opencloning_read_only'

# No workspace has this id (ids start at 1), so scoping to it hides all workspace rows.
_NO_WORKSPACE = 0

# Models that do not belong to a workspace.
GLOBAL_MODELS: tuple[type[Base], ...] = (User, Workspace, WorkspaceMembership)
# Models with their own workspace_id column (subclasses included).
DIRECT_WORKSPACE_MODELS: tuple[type[Base], ...] = (InputEntity, Tag, Line, SequenceInstance)
# Models that belong to the workspace of the sequence they are attached to (subclasses included).
INDIRECT_WORKSPACE_MODELS: tuple[type[Base], ...] = (SequencingFile, Source, SourceInput)


class WorkspaceScopeError(RuntimeError):
    """A query or write escaped the workspace scope of the session. This is a programming error."""


class RequestSession(Session):
    """Session used by API requests (``get_db``). It behaves exactly like a plain ``Session``, which is scoped as well.

    Not to be confused with SQLAlchemy's ``scoped_session`` (a thread-local session registry).
    """


class UnscopedSession(Session):
    """Explicit opt-out of workspace scoping: sees and writes all workspaces. Only for tests."""


def bind_workspace(session: Session, workspace_id: int, *, read_only: bool = False) -> None:
    """Scope all subsequent ORM queries and writes of the session to ``workspace_id``.

    With ``read_only``, the session also rejects every write from now on.
    """
    current = session.info.get(_WORKSPACE_ID_KEY)
    if current is not None and current != workspace_id:
        raise WorkspaceScopeError(f'Session is already bound to workspace {current}, cannot bind {workspace_id}')
    session.info[_WORKSPACE_ID_KEY] = workspace_id
    if read_only:
        session.info[_READ_ONLY_KEY] = True
        # The transaction that is already open (e.g. from authentication) is switched now,
        # later transactions are switched by _make_new_transaction_read_only.
        if session.in_transaction():
            session.connection().exec_driver_sql('SET TRANSACTION READ ONLY')


def _effective_workspace_id(session: Session) -> int | None:
    """Workspace the session is scoped to (``_NO_WORKSPACE`` if unbound), or None for an UnscopedSession."""
    if isinstance(session, UnscopedSession):
        return None
    return session.info.get(_WORKSPACE_ID_KEY, _NO_WORKSPACE)


# Private alias, so that the EXISTS below never auto-correlates with an input_entity of the enclosing query
_input_entity = InputEntity.__table__.alias('workspace_scope_input_entity')


def _belongs_to_workspace(input_entity_id, workspace_id: int):
    """Correlated EXISTS: the input entity (sequence) with this id is in the workspace."""
    return exists().where(_input_entity.c.id == input_entity_id, _input_entity.c.workspace_id == workspace_id)


def _workspace_criteria(workspace_id: int) -> tuple:
    return (
        with_loader_criteria(InputEntity, lambda cls: cls.workspace_id == workspace_id, include_aliases=True),
        with_loader_criteria(Tag, lambda cls: cls.workspace_id == workspace_id, include_aliases=True),
        with_loader_criteria(Line, lambda cls: cls.workspace_id == workspace_id, include_aliases=True),
        with_loader_criteria(SequenceInstance, lambda cls: cls.workspace_id == workspace_id, include_aliases=True),
        with_loader_criteria(
            SequencingFile,
            lambda cls: _belongs_to_workspace(cls.sequence_id, workspace_id),
            include_aliases=True,
        ),
        with_loader_criteria(Source, lambda cls: _belongs_to_workspace(cls.id, workspace_id), include_aliases=True),
        with_loader_criteria(
            SourceInput,
            lambda cls: _belongs_to_workspace(cls.source_id, workspace_id),
            include_aliases=True,
        ),
    )


@event.listens_for(Session, 'do_orm_execute')
def _scope_orm_statement(state: ORMExecuteState) -> None:
    # Column loads refresh objects already in the session (expired or deferred attributes), they are not filtered
    if not state.is_select or not state.is_orm_statement or state.is_column_load:
        return
    session = state.session
    workspace_id = _effective_workspace_id(session)
    if workspace_id is None:
        return
    if workspace_id == _NO_WORKSPACE:
        scoped_models = sorted(
            mapper.class_.__name__ for mapper in state.all_mappers if not issubclass(mapper.class_, GLOBAL_MODELS)
        )
        if scoped_models:
            raise WorkspaceScopeError(
                f"Query on workspace data ({', '.join(scoped_models)}) in a session not bound to a workspace"
            )
    # Also applied to relationship loads, so that objects created in this session are covered
    state.statement = state.statement.options(*_workspace_criteria(workspace_id))


@event.listens_for(Session, 'after_begin')
def _make_new_transaction_read_only(session: Session, transaction, connection) -> None:
    if session.info.get(_READ_ONLY_KEY):
        connection.exec_driver_sql('SET TRANSACTION READ ONLY')


@event.listens_for(Session, 'before_flush')
def _check_written_rows_workspace(session: Session, *_) -> None:
    workspace_id = _effective_workspace_id(session)
    if workspace_id is None:
        return
    if session.info.get(_READ_ONLY_KEY) and (
        session.new or session.deleted or any(session.is_modified(obj) for obj in session.dirty)
    ):
        raise WorkspaceScopeError('Write attempted in a read-only session')
    for obj in [*session.new, *session.dirty, *session.deleted]:
        if isinstance(obj, DIRECT_WORKSPACE_MODELS) and obj.workspace_id != workspace_id:
            raise WorkspaceScopeError(
                f'{type(obj).__name__} of workspace {obj.workspace_id} '
                f'written in a session bound to workspace {workspace_id}'
            )
