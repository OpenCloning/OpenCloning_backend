"""Template sequence endpoints."""

from collections import Counter
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from opencloning_db.apimodels import (
    SequenceRef,
    TemplateSequenceBulkRow,
    TemplateSequenceCreate,
    sequence_ref,
)
from opencloning_db.models import TemplateSequence, WorkspaceRole, assert_template_sequence_name_available
from opencloning_db.workspace_deps import (
    WorkspaceContext,
    get_editor_workspace_ctx,
    get_tag_in_workspace_for_user,
    get_viewer_workspace_ctx,
)

router = APIRouter(tags=['template_sequences'])


def _frequency_duplicates(values: list[str]) -> set[str]:
    return {value for value, count in Counter(values).items() if count > 1}


def _template_sequence_bulk_rows_with_flags(
    items: list[TemplateSequenceCreate],
    session,
    workspace_id: int,
) -> list[TemplateSequenceBulkRow]:
    normalized_names = [item.name.casefold() for item in items]
    duplicate_names = _frequency_duplicates(normalized_names)

    db_name_matches = set(
        session.scalars(
            select(func.lower(TemplateSequence.name)).where(
                TemplateSequence.workspace_id == workspace_id,
                func.lower(TemplateSequence.name).in_(set(normalized_names)),
            )
        ).all()
    )

    rows: list[TemplateSequenceBulkRow] = []
    for item, name_norm in zip(items, normalized_names):
        rows.append(
            TemplateSequenceBulkRow(
                name=item.name,
                sequence_type=item.sequence_type,
                name_exists=name_norm in db_name_matches,
                name_duplicated=name_norm in duplicate_names,
            )
        )
    return rows


def _has_any_template_conflict(rows: list[TemplateSequenceBulkRow]) -> bool:
    return any(row.name_exists or row.name_duplicated for row in rows)


@router.post('/template_sequences', response_model=SequenceRef)
def post_template_sequence(
    ctx: Annotated[WorkspaceContext, Depends(get_editor_workspace_ctx)],
    body: TemplateSequenceCreate,
):
    _, session, workspace_id = ctx.destructure()
    assert_template_sequence_name_available(session, workspace_id=workspace_id, name=body.name)
    template_sequence = TemplateSequence.from_create(
        name=body.name,
        sequence_type=body.sequence_type,
        ctx=ctx,
    )
    session.add(template_sequence)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Template sequence '{body.name}' already exists in this workspace",
        ) from None
    session.refresh(template_sequence)
    return sequence_ref(template_sequence)


@router.post('/template_sequences/validate-upload', response_model=list[TemplateSequenceBulkRow])
def validate_upload_template_sequences(
    ctx: Annotated[WorkspaceContext, Depends(get_viewer_workspace_ctx)],
    items: list[TemplateSequenceCreate],
):
    _, session, workspace_id = ctx.destructure()
    return _template_sequence_bulk_rows_with_flags(items, session, workspace_id)


@router.post('/template_sequences/bulk', response_model=list[SequenceRef])
def post_template_sequences_bulk(
    ctx: Annotated[WorkspaceContext, Depends(get_editor_workspace_ctx)],
    items: list[TemplateSequenceCreate],
    tags: list[int] = Query(description='Tag IDs to apply to all created template sequences', default_factory=list),
):
    current_user, session, workspace_id = ctx.destructure()
    workspace_tags = [
        get_tag_in_workspace_for_user(session, current_user, workspace_id, tag_id, WorkspaceRole.editor)
        for tag_id in sorted(set(tags))
    ]
    validation_rows = _template_sequence_bulk_rows_with_flags(items, session, workspace_id)
    if _has_any_template_conflict(validation_rows):
        return JSONResponse(
            status_code=409,
            content=[row.model_dump(mode='json') for row in validation_rows],
        )

    db_items = [
        TemplateSequence.from_create(name=item.name, sequence_type=item.sequence_type, ctx=ctx) for item in items
    ]
    for db_item in db_items:
        db_item.tags.extend(workspace_tags)
    session.add_all(db_items)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        conflict_rows = _template_sequence_bulk_rows_with_flags(items, session, workspace_id)
        return JSONResponse(
            status_code=409,
            content=[row.model_dump(mode='json') for row in conflict_rows],
        )

    for db_item in db_items:
        session.refresh(db_item)
    return [sequence_ref(db_item) for db_item in db_items]
