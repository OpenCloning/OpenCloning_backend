"""
Automatic workspace scoping for ORM queries.

Inside an API request, the session is bound to the selected workspace (``bind_workspace``, called by the
workspace context dependencies). From then on, every ORM SELECT on workspace data is filtered to that
workspace, however it is written: ``session.get``, ``select``, legacy ``query()``, relationship loads and
subqueries. Rows of other workspaces behave as if they did not exist, and writing them is refused at flush.

Request sessions that are not bound to a workspace (e.g. the ``/workspaces`` routes) may only query global
models (users, workspaces, memberships). Sessions created outside requests (CLI, seeding, tests) are not
affected.

There is no opt-out: code that has to cross workspaces must not use a request session.

Limits: core table queries (``select(table.c...)``) and raw SQL are not filtered.
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

_REQUIRE_WORKSPACE_KEY = 'opencloning_require_workspace'
_WORKSPACE_ID_KEY = 'opencloning_workspace_id'

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


def require_workspace_scope(session: Session) -> None:
    """Mark a request session: workspace data can only be queried once a workspace is bound."""
    session.info[_REQUIRE_WORKSPACE_KEY] = True


def bind_workspace(session: Session, workspace_id: int) -> None:
    """Scope all subsequent ORM queries and writes of the session to ``workspace_id``."""
    current = session.info.get(_WORKSPACE_ID_KEY)
    if current is not None and current != workspace_id:
        raise WorkspaceScopeError(f'Session is already bound to workspace {current}, cannot bind {workspace_id}')
    session.info[_WORKSPACE_ID_KEY] = workspace_id


def _effective_workspace_id(session: Session) -> int | None:
    """Workspace the session is scoped to, or None if the session is not scoped."""
    workspace_id = session.info.get(_WORKSPACE_ID_KEY)
    if workspace_id is None and session.info.get(_REQUIRE_WORKSPACE_KEY):
        return _NO_WORKSPACE
    return workspace_id


# Private alias, so that the EXISTS below never auto-correlates with an input_entity of the enclosing query
_input_entity = InputEntity.__table__.alias('workspace_scope_input_entity')


def _belongs_to_workspace(input_entity_id, workspace_id: int):
    """Correlated EXISTS: the input entity (sequence) with this id is in the workspace."""
    return (
        exists()
        .where(_input_entity.c.id == input_entity_id, _input_entity.c.workspace_id == workspace_id)
        .correlate_except(_input_entity)
    )


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


@event.listens_for(Session, 'before_flush')
def _check_written_rows_workspace(session: Session, *_) -> None:
    workspace_id = _effective_workspace_id(session)
    if workspace_id is None:
        return
    for obj in [*session.new, *session.dirty, *session.deleted]:
        if isinstance(obj, DIRECT_WORKSPACE_MODELS) and obj.workspace_id != workspace_id:
            raise WorkspaceScopeError(
                f'{type(obj).__name__} of workspace {obj.workspace_id} '
                f'written in a session bound to workspace {workspace_id}'
            )
