"""Primer endpoints."""

from collections import Counter
import re
from typing import Annotated

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from opencloning_db.apimodels import (
    IdResponse,
    PrimerBulkSubmission,
    PrimerBulkRow,
    PrimerRef,
    SequenceRef,
    TagRead,
    sequence_ref,
    PrimerUpdate,
    PrimerCreate,
)
from fastapi_pagination import Page
from fastapi_pagination.ext.sqlalchemy import paginate
from opencloning_db.models import InputEntity, Primer, Sequence, Source, SourceInput, Tag, WorkspaceRole
from pydantic import create_model
from opencloning_db.workspace_deps import (
    WorkspaceContext,
    get_editor_workspace_ctx,
    get_primer_in_workspace_for_user,
    get_viewer_workspace_ctx,
)

router = APIRouter(tags=['primers'])


def _normalize_name(value: str) -> str:
    return value.strip().casefold()


def _normalize_sequence(value: str) -> str:
    return value.upper()


def _normalize_uid(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if stripped == '':
        return None
    return stripped.casefold()


def _frequency_duplicates(values: list[str]) -> set[str]:
    return {value for value, count in Counter(values).items() if count > 1}


def _is_invalid_sequence(value: str) -> bool:
    return len(value) <= 2 or re.fullmatch(r'[ACGTacgt]+', value) is None


def _primer_bulk_rows_with_flags(
    primers: list[PrimerBulkSubmission],
    session,
    workspace_id: int,
) -> list[PrimerBulkRow]:
    normalized_names = [_normalize_name(primer.name) for primer in primers]
    normalized_sequences = [_normalize_sequence(primer.sequence) for primer in primers]
    normalized_uids = [_normalize_uid(primer.uid) for primer in primers]

    duplicate_names = _frequency_duplicates(normalized_names)
    duplicate_sequences = _frequency_duplicates(normalized_sequences)
    duplicate_uids = _frequency_duplicates([uid for uid in normalized_uids if uid is not None])

    db_name_matches = set(
        session.scalars(
            select(func.lower(func.trim(Primer.name))).where(
                Primer.workspace_id == workspace_id,
                func.lower(func.trim(Primer.name)).in_(set(normalized_names)),
            )
        ).all()
    )
    db_sequence_matches = set(
        session.scalars(
            select(func.upper(Primer.sequence)).where(
                Primer.workspace_id == workspace_id,
                func.upper(Primer.sequence).in_(set(normalized_sequences)),
            )
        ).all()
    )
    uid_candidates = {uid for uid in normalized_uids if uid is not None}
    db_uid_matches = set(
        session.scalars(
            select(func.lower(func.trim(Primer.uid))).where(
                Primer.workspace_id == workspace_id,
                Primer.uid.isnot(None),
                func.lower(func.trim(Primer.uid)).in_(uid_candidates),
            )
        ).all()
    )

    rows: list[PrimerBulkRow] = []
    for primer, name_norm, sequence_norm, uid_norm in zip(
        primers, normalized_names, normalized_sequences, normalized_uids
    ):
        rows.append(
            PrimerBulkRow(
                name=primer.name,
                sequence=primer.sequence,
                uid=primer.uid,
                sequence_invalid=_is_invalid_sequence(primer.sequence),
                name_exists=name_norm in db_name_matches,
                sequence_exists=sequence_norm in db_sequence_matches,
                uid_exists=uid_norm is not None and uid_norm in db_uid_matches,
                name_duplicated=name_norm in duplicate_names,
                sequence_duplicated=sequence_norm in duplicate_sequences,
                uid_duplicated=uid_norm in duplicate_uids,
            )
        )
    return rows


def _has_any_conflict(rows: list[PrimerBulkRow], strict: bool) -> bool:
    if any(row.uid_duplicated or row.uid_exists or row.sequence_invalid for row in rows):
        return True
    if not strict:
        return False

    return any(
        row.name_exists or row.sequence_exists or row.name_duplicated or row.sequence_duplicated for row in rows
    )


@router.get('/primers', response_model=Page[PrimerRef])
def get_primers(
    ctx: Annotated[WorkspaceContext, Depends(get_viewer_workspace_ctx)],
    tags: list[int] = Query(description='Filter primers by tag IDs', default_factory=list),
    name: str | None = Query(description='Filter primers by name (case-insensitive substring match)', default=None),
    uid: str | None = Query(
        description='Filter primers by sample uid (case-insensitive substring match)', default=None
    ),
    has_uid: bool = Query(description='Filter primers by whether they have a uid', default=False),
):
    current_user, session, workspace_id = ctx

    query = select(Primer).where(Primer.workspace_id == workspace_id).options(selectinload(InputEntity.tags))
    if tags:
        query = query.where(InputEntity.tags.any(and_(Tag.id.in_(tags), Tag.workspace_id == workspace_id)))
    if name is not None:
        query = query.where(Primer.name.ilike(f"%{name}%"))
    if uid is not None:
        query = query.where(Primer.uid.ilike(f"%{uid}%"))
    if has_uid is True:
        query = query.where(Primer.uid.isnot(None))
    return paginate(session, query)


@router.post('/primers', response_model=IdResponse)
def post_primer(
    ctx: Annotated[WorkspaceContext, Depends(get_editor_workspace_ctx)],
    primer: PrimerCreate,
):
    """Submit a standalone primer (unlinked to any cloning strategy)."""
    current_user, session, workspace_id = ctx

    if primer.uid is not None:
        existing_uid = session.scalar(
            select(Primer).where(Primer.uid == primer.uid, Primer.workspace_id == workspace_id)
        )
        if existing_uid is not None:
            raise HTTPException(status_code=409, detail=f"Primer UID '{primer.uid}' already exists")

    db_primer = Primer(
        name=primer.name,
        uid=primer.uid,
        workspace_id=workspace_id,
        uid_workspace_id=workspace_id,
        sequence=primer.sequence,
    )

    session.add(db_primer)
    session.commit()
    session.refresh(db_primer)
    return IdResponse(id=db_primer.id)


@router.post('/primers/validate-upload', response_model=list[PrimerBulkRow])
def validate_upload_primers(
    ctx: Annotated[WorkspaceContext, Depends(get_viewer_workspace_ctx)],
    primers: list[PrimerBulkSubmission],
):
    current_user, session, workspace_id = ctx
    return _primer_bulk_rows_with_flags(primers, session, workspace_id)


@router.post('/primers/bulk', response_model=list[PrimerRef])
def post_primers_bulk(
    ctx: Annotated[WorkspaceContext, Depends(get_editor_workspace_ctx)],
    primers: list[PrimerBulkSubmission],
    strict: bool = Query(description='Fail if duplicate name or sequence exists', default=True),
):
    current_user, session, workspace_id = ctx
    validation_rows = _primer_bulk_rows_with_flags(primers, session, workspace_id)
    if _has_any_conflict(validation_rows, strict):
        return JSONResponse(
            status_code=409,
            content=[row.model_dump(mode='json') for row in validation_rows],
        )

    db_primers: list[Primer] = []
    for primer in primers:
        db_primers.append(
            Primer(
                name=primer.name,
                uid=primer.uid,
                workspace_id=workspace_id,
                uid_workspace_id=workspace_id,
                sequence=primer.sequence,
            )
        )
    session.add_all(db_primers)
    try:
        session.commit()
    except IntegrityError:
        # In case someone would have created the primers in the meantime, we need to return the conflict rows
        session.rollback()
        conflict_rows = _primer_bulk_rows_with_flags(primers, session, workspace_id)
        return JSONResponse(
            status_code=409,
            content=[row.model_dump(mode='json') for row in conflict_rows],
        )

    for db_primer in db_primers:
        session.refresh(db_primer)

    return [
        PrimerRef(
            id=db_primer.id,
            name=db_primer.name,
            sequence=db_primer.sequence,
            uid=db_primer.uid,
            tags=[TagRead(id=t.id, name=t.name) for t in db_primer.tags],
        )
        for db_primer in db_primers
    ]


@router.get('/primers/{primer_id}', response_model=PrimerRef)
def get_primer(
    primer_id: int,
    ctx: Annotated[WorkspaceContext, Depends(get_viewer_workspace_ctx)],
):
    current_user, session, workspace_id = ctx
    primer = get_primer_in_workspace_for_user(session, current_user, workspace_id, primer_id, WorkspaceRole.viewer)

    return PrimerRef(
        id=primer.id,
        name=primer.name,
        sequence=primer.sequence,
        uid=primer.uid,
        tags=[TagRead(id=t.id, name=t.name) for t in primer.tags],
    )


@router.get(
    '/primers/{primer_id}/sequences',
    response_model=create_model('PrimerSequences', templates=list[SequenceRef], products=list[SequenceRef]),
)
def get_primer_sequences(
    primer_id: int,
    ctx: Annotated[WorkspaceContext, Depends(get_viewer_workspace_ctx)],
):
    """Get sequences linked to a primer."""
    current_user, session, workspace_id = ctx
    # Check that the user has access to the primer and the primer exists
    get_primer_in_workspace_for_user(session, current_user, workspace_id, primer_id, WorkspaceRole.viewer)

    # 1) All source IDs where this primer was an input
    primer_source_ids = select(SourceInput.source_id).where(SourceInput.input_entity_id == primer_id)
    # 2) All sequences that were inputs to those same sources
    template_sequences = (
        select(Sequence)
        .join(
            SourceInput,
            SourceInput.input_entity_id == Sequence.id,
        )
        .where(
            SourceInput.source_id.in_(primer_source_ids),
            Sequence.workspace_id == Primer.workspace_id,  # Safety check TODO: Maybe remove?
        )
        .distinct()
    )
    # 3) All sequences that were outputs of those same sources
    product_sequences = (
        select(Sequence)
        .join(Source)
        .where(
            Source.id.in_(primer_source_ids),
            Sequence.workspace_id == Primer.workspace_id,  # Safety check TODO: Maybe remove?
        )
    )
    templates = session.execute(template_sequences).scalars().all()
    products = session.execute(product_sequences).scalars().all()

    return {
        'templates': [sequence_ref(s) for s in templates],
        'products': [sequence_ref(s) for s in products],
    }


@router.patch('/primers/{primer_id}', response_model=PrimerRef)
def patch_primer(
    primer_id: int,
    body: PrimerUpdate,
    ctx: Annotated[WorkspaceContext, Depends(get_editor_workspace_ctx)],
):
    """
    Update primer name and/or uid. Sending an empty or whitespace-only uid clears it.

    Note: the primer "type" is fixed by polymorphic identity and cannot be changed.
    """

    current_user, session, workspace_id = ctx
    primer = get_primer_in_workspace_for_user(session, current_user, workspace_id, primer_id, WorkspaceRole.editor)
    if body.name is not None:
        primer.name = body.name
    if body.uid is not None:
        if body.uid == '':
            primer.uid = None
        else:
            existing_primer = session.scalar(
                select(Primer).where(Primer.uid == body.uid, Primer.workspace_id == workspace_id)
            )
            if existing_primer is not None:
                raise HTTPException(status_code=409, detail=f"Primer UID '{body.uid}' already exists")
            primer.uid = body.uid

    session.commit()
    session.refresh(primer)

    return PrimerRef(
        id=primer.id,
        name=primer.name,
        sequence=primer.sequence,
        uid=primer.uid,
        tags=[TagRead(id=t.id, name=t.name) for t in primer.tags],
    )
