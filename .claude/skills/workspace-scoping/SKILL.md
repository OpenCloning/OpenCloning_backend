---
name: workspace-scoping
description: "Use when adding, removing or changing SQLAlchemy models in opencloning-db, writing queries or endpoints that touch workspace data, writing migrations that touch workspace columns, or debugging WorkspaceScopeError, missing rows, or cross-workspace IntegrityErrors."
---

# Workspace Scoping

Every row of workspace data belongs to exactly one workspace. A request must never read or write rows of another workspace. Three layers enforce this:

1. **Automatic ORM scoping** (`packages/opencloning-db/src/opencloning_db/workspace_scope.py`) filters every query in a request session.
2. **Database constraints** (composite foreign keys) keep the workspace copies used for UID uniqueness consistent.
3. **Flush validators** (`_validate_cross_workspace_invariants` in `models.py`) reject links between rows of different workspaces that the database does not enforce.

## Source of truth

- Scoping module: `packages/opencloning-db/src/opencloning_db/workspace_scope.py`
- Models and flush validators: `packages/opencloning-db/src/opencloning_db/models.py`
- Session marking: `get_db` in `deps.py`, and `override_get_db` in `tests/conftest.py`
- Session binding: `get_viewer_workspace_ctx` / `get_editor_workspace_ctx` in `workspace_deps.py`
- Tests: `packages/opencloning-db/tests/test_workspace_scope.py`

## How scoping works

**Session states.** The state lives in `session.info`, not in a ContextVar: FastAPI runs sync dependencies and endpoints in different threadpool contexts.

| Session | Created by | Behaviour |
|---|---|---|
| Unscoped | plain `Session(engine)`: CLI, `init_db`, seeding, tests | no filtering, no write guard |
| Marked request session | `get_db` calls `require_workspace_scope(session)` | only `User`, `Workspace` and `WorkspaceMembership` may be queried; anything else raises `WorkspaceScopeError` |
| Bound request session | workspace context dependency calls `bind_workspace(session, workspace_id)` after the membership check | every ORM SELECT is filtered to that workspace; writes to other workspaces are refused |

**Reads.** The `do_orm_execute` listener `_scope_orm_statement` adds `with_loader_criteria` rules (`_workspace_criteria`) to every ORM SELECT, whatever its form:
- `session.get`, `select`, and legacy `query()`;
- lazy and `selectinload` relationship loads;
- joins and subqueries.

Rows of other workspaces behave as if they did not exist. `session.get` returns `None`, and endpoints answer 404, the same as for a nonexistent ID. Column loads (refreshes of expired or deferred attributes) are not filtered.

**Writes.** The `before_flush` listener `_check_written_rows_workspace` raises `WorkspaceScopeError` when a new, changed or deleted row of a `DIRECT_WORKSPACE_MODELS` class has a `workspace_id` different from the bound workspace, including `None`. It never fills the value in: creation code must set it, normally from `ctx.workspace_id` through the model's `from_create` / `from_pydantic` constructor, or `workspace_id=ctx.workspace_id`.

**Not covered:**
- Core table queries (`select(table.c...)`) and raw SQL are not filtered. Don't use them for workspace data in request code.
- There is no opt-out inside a request session. Code that must cross workspaces (admin tooling) uses a plain `Session(engine)`.

## Model classification

Every mapped class must fall under exactly one root. `test_every_model_is_classified` enforces this.

| Category | Tuple in `workspace_scope.py` | Rule in `_workspace_criteria` | Current roots |
|---|---|---|---|
| Global (not workspace data) | `GLOBAL_MODELS` | none | `User`, `Workspace`, `WorkspaceMembership` |
| Direct (own `workspace_id` column) | `DIRECT_WORKSPACE_MODELS` | `cls.workspace_id == workspace_id` | `InputEntity`, `Tag`, `Line`, `SequenceInstance` |
| Indirect (workspace of the input entity it hangs off) | `INDIRECT_WORKSPACE_MODELS` | `_belongs_to_workspace(<column holding an input_entity id>, workspace_id)` | `SequencingFile`, `Source`, `SourceInput` |

A rule registered on a root also applies to its subclasses. For example, `InputEntity` covers `Sequence`, `TemplateSequence` and `Primer`, and `SequenceInstance` covers `SequenceSample` and `SequenceInLine`.

`_belongs_to_workspace` is a correlated `EXISTS` on a private alias of `input_entity`. Keep the alias: without it, the subquery auto-correlates with an `input_entity` of the enclosing query and breaks.

## Workspace copies (UID uniqueness)

`Primer` and `SequenceSample` keep a copy of the workspace in their own table, because the per-workspace UID unique index (`workspace_id, lower(uid)`) needs both columns in one table. The copies are kept correct as follows:
- **One attribute, two columns.** `workspace_id = column_property(Column('workspace_id', ...), <Parent>.__table__.c.workspace_id)` writes both columns.
- **Composite foreign keys enforce equality in the database:**
  - `primer (id, workspace_id) → input_entity (id, workspace_id)`;
  - `sequence_instance (sequence_id, workspace_id) → input_entity (id, workspace_id)`;
  - `sequence_sample (id, workspace_id) → sequence_instance (id, workspace_id)`.
- **Each referenced table needs a unique constraint** on exactly the referenced pair (`uq_input_entity_id_workspace`, `uq_sequence_instance_id_workspace`). Postgres refuses the foreign key otherwise.
- **The second foreign key to the parent makes SQLAlchemy ambiguous.** Set an explicit `inherit_condition` on the subclass and `foreign_keys` on the affected relationships.

## Checklist: adding a model

1. **Classify it.**
   - **A subclass of an existing root:** nothing to add in `workspace_scope.py`.
   - **Global:** add it to `GLOBAL_MODELS`. This is rare; only data that truly belongs to no workspace.
   - **Has its own `workspace_id`:** add it to `DIRECT_WORKSPACE_MODELS` and add a `cls.workspace_id == workspace_id` rule to `_workspace_criteria`.
   - **Belongs to an input entity:** add it to `INDIRECT_WORKSPACE_MODELS` and add a `_belongs_to_workspace(cls.<input_entity id column>, workspace_id)` rule.
   - **Belongs to some other parent** (for example a `Line`): either give it its own `workspace_id` with a composite FK to the parent's `(id, workspace_id)`, which makes it direct, or write a new `EXISTS` helper on a private alias of the parent table.
2. **Set the workspace at creation.** Add a `from_create(..., ctx)` constructor, or pass `workspace_id=ctx.workspace_id` explicitly. Never rely on a flush to fill it.
3. **Needs a value unique per workspace?** Put a workspace copy next to the value and follow the workspace-copies pattern above: a single attribute, a composite FK, a unique constraint on the parent pair, and SQLAlchemy disambiguation.
4. **Links to other workspace rows** (a foreign key, or an association table to `Tag`, `Line`, an input entity)? Either enforce same-workspace in the database with a composite FK, or add a validator to `_validate_cross_workspace_invariants` in `models.py`.
5. **Endpoints:**
   - depend on `get_viewer_workspace_ctx` / `get_editor_workspace_ctx`;
   - resolve client-supplied IDs with the `get_*_in_workspace_for_user` helpers in `workspace_deps.py`;
   - keep explicit `workspace_id` filters in shared helpers that can run in unscoped sessions.
6. **Migration:** generate with Alembic autogenerate, then review it (see Migrations).

## Checklist: removing or changing a model

- **Removing:** delete it from its tuple, delete its rule in `_workspace_criteria`, and remove it from the scoping tests (seed, `SCOPED_MODELS`, API paths).
- **Renaming or moving its workspace column, or changing the parent an indirect model hangs off:** update its rule. For direct models, the write guard reads `obj.workspace_id`, so keep that attribute name.
- **Turning an indirect model into a direct one** (adding a `workspace_id`): move it between the tuples, replace the `EXISTS` rule with the plain rule, and add a composite FK to the parent so the copy can't drift.
- **A flush validator becomes enforced by a constraint:** remove it, and switch its tests to expect `IntegrityError`.

## Tests to add or update (`tests/test_workspace_scope.py` unless noted)

- **Classification:** `test_every_model_is_classified` fails automatically for an unclassified model. Fix the classification rather than the test.
- **Seed:** create one row of the model in `_seed_workspace`, so both workspaces get one, and return its ID under the model's class name.
- **Read isolation:** add the model to `SCOPED_MODELS`, which feeds `test_bound_session_hides_other_workspace`. That test checks `session.get`, column selects, `query()` and subqueries. Models without a single `id` primary key need a dedicated test, like `test_bound_session_hides_other_workspace_source_inputs`.
- **Relationships:** if the model is reached through a relationship that could cross workspaces, extend `test_bound_session_filters_relationship_loads`. It inserts a cross-workspace link with raw SQL and asserts it stays invisible.
- **API:** if an endpoint loads it by ID, add the path to `test_api_foreign_id_same_as_missing`. A foreign ID must return the same 404 as a missing one.
- **Workspace copy:** add the model to `test_database_rejects_inconsistent_workspace_copy`.
- **Cross-workspace validator:** add tests in `tests/test_models.py`, `TestCrossWorkspaceHooks`.
- **Data migrations** (for example a new non-null column on an existing table): add a `TestMigration_<revision>` class in `tests/test_migrations.py`. It downgrades to the previous revision, seeds rows with raw SQL, upgrades, and asserts the backfilled values.
- **Router tests that asserted 403** for an ID in a workspace the user doesn't belong to now get 404. 403 remains only for a header workspace the user isn't a member of, or an insufficient role.

## Migrations

Generate from the repository root, with Postgres running and the dev database at the previous head:

```bash
source .env.dev
ALEMBIC_CFG=packages/opencloning-db/alembic.ini
uv run alembic -c "$ALEMBIC_CFG" revision --autogenerate -m "short description"
```

Review the generated file:
- **New `NOT NULL` column on an existing table:** add it as nullable, backfill it with `op.execute(...)`, then `alter_column(..., nullable=False)`.
- **Order:** create unique constraints before the foreign keys that reference them.
- **Dropped constraints:** check they are restored in `downgrade()`.

Adding a foreign key validates all existing rows. An inconsistent row makes the migration fail and roll back.

## Running the tests

The test schema comes from Alembic, so a model change needs its migration before the DB tests can run (see the `postgres-test-workflow` skill).

```bash
.venv/bin/python -m pytest packages/opencloning-db/tests/test_workspace_scope.py -q
.venv/bin/python -m pytest packages/opencloning-db/tests packages/opencloning-cli/tests -q
```
