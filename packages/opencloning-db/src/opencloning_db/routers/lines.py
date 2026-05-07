"""Line (engineered strain / cell line) endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Column, Select, and_, exists, select
from sqlalchemy.orm import selectinload

from opencloning_db.apimodels import (
    DeletedResponse,
    LineCreate,
    LineRef,
    LineUpdate,
    SequenceInLineRef,
    TagRead,
    sequence_ref,
)
from fastapi_pagination import Page
from fastapi_pagination.ext.sqlalchemy import paginate
from opencloning_db.models import Line, Sequence, SequenceInLine, SequenceType, Tag, WorkspaceRole
from opencloning_db.workspace_deps import (
    WorkspaceContext,
    get_editor_workspace_ctx,
    get_line_in_workspace_for_user,
    get_sequence_in_workspace_for_user,
    get_viewer_workspace_ctx,
)

router = APIRouter(tags=['lines'])


def _sil_ref(sil: SequenceInLine) -> SequenceInLineRef:
    """Build a SequenceInLineRef from a SequenceInLine ORM instance."""
    seq = sil.sequence
    return SequenceInLineRef(
        id=sil.id,
        sequence=sequence_ref(seq),
    )


def _line_ref(line: Line) -> LineRef:
    return LineRef(
        id=line.id,
        uid=line.uid,
        sequences_in_line=[_sil_ref(sil) for sil in line.sequences_in_line],
        parent_ids=line.parent_ids,
        tags=[TagRead(id=tag.id, name=tag.name) for tag in line.tags],
    )


def get_line_subquery(line_id_col: Column, sequence_type: SequenceType, name: str) -> Select:
    subq = (
        select(1)
        .select_from(SequenceInLine)
        .join(Sequence, SequenceInLine.sequence_id == Sequence.id)
        .where(
            SequenceInLine.line_id == line_id_col,
            Sequence.sequence_type == sequence_type,
            Sequence.name.ilike(f"%{name}%"),
        )
    )
    return subq


@router.get('/lines', response_model=Page[LineRef])
def get_lines(
    ctx: Annotated[WorkspaceContext, Depends(get_viewer_workspace_ctx)],
    tags: list[int] = Query(description='Filter lines by tag IDs', default_factory=list),
    genotype: str | None = Query(
        description='Filter lines by genotype (case-insensitive substring to match allele names), spaces are AND',
        default=None,
    ),
    plasmid: str | None = Query(
        description='Filter lines by plasmid name (case-insensitive substring match), spaces are AND', default=None
    ),
    uid: str | None = Query(description='Filter lines by uid (case-insensitive substring match)', default=None),
):
    current_user, session, workspace_id = ctx

    query = (
        select(Line)
        .options(
            selectinload(Line.sequences_in_line)
            .selectinload(SequenceInLine.sequence)
            .options(selectinload(Sequence.tags)),
            selectinload(Line.parents),
            selectinload(Line.tags),
        )
        .where(Line.workspace_id == workspace_id)
    )
    if tags:
        query = query.where(Line.tags.any(and_(Tag.id.in_(tags), Tag.workspace_id == workspace_id)))
    if genotype is not None:
        for allele_bit in genotype.strip().split(' '):
            subq = get_line_subquery(Line.id, SequenceType.allele, allele_bit)
            query = query.where(exists(subq))
    if plasmid is not None:
        for plasmid_bit in plasmid.strip().split(' '):
            subq = get_line_subquery(Line.id, SequenceType.plasmid, plasmid_bit)
            query = query.where(exists(subq))
    if uid is not None:
        query = query.where(Line.uid.ilike(f"%{uid}%"))
    return paginate(session, query, transformer=lambda items: [_line_ref(line) for line in items])


@router.get('/lines/{line_id}', response_model=LineRef)
def get_line(
    line_id: int,
    ctx: Annotated[WorkspaceContext, Depends(get_viewer_workspace_ctx)],
):
    """Get a single engineered strain / cell line by id."""
    current_user, session, workspace_id = ctx
    line = get_line_in_workspace_for_user(session, current_user, workspace_id, line_id, WorkspaceRole.viewer)
    return _line_ref(line)


@router.get('/lines/{line_id}/children', response_model=list[LineRef])
def get_line_children(
    line_id: int,
    ctx: Annotated[WorkspaceContext, Depends(get_viewer_workspace_ctx)],
):
    """List direct children of a line."""
    current_user, session, workspace_id = ctx
    line = get_line_in_workspace_for_user(session, current_user, workspace_id, line_id, WorkspaceRole.viewer)
    return [_line_ref(child) for child in line.children]


@router.post('/lines', response_model=LineRef)
def post_line(
    ctx: Annotated[WorkspaceContext, Depends(get_editor_workspace_ctx)],
    body: LineCreate,
):
    """Create a new engineered strain / cell line."""
    current_user, session, workspace_id = ctx

    existing = session.query(Line).filter_by(uid=body.uid, workspace_id=workspace_id).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Line UID '{body.uid}' already exists")

    allele_seqs = [
        get_sequence_in_workspace_for_user(
            session,
            current_user,
            workspace_id,
            sid,
            WorkspaceRole.editor,
            expected_type=SequenceType.allele,
        )
        for sid in body.allele_ids
    ]
    plasmid_seqs = [
        get_sequence_in_workspace_for_user(
            session,
            current_user,
            workspace_id,
            sid,
            WorkspaceRole.editor,
            expected_type=SequenceType.plasmid,
        )
        for sid in body.plasmid_ids
    ]

    parents: list[Line] = []
    for parent_id in body.parent_ids:
        parents.append(
            get_line_in_workspace_for_user(
                session,
                current_user,
                workspace_id,
                parent_id,
                WorkspaceRole.editor,
            )
        )

    line = Line(uid=body.uid, workspace_id=workspace_id)
    line.parents = parents
    line.sequences_in_line = [SequenceInLine(sequence=seq) for seq in allele_seqs] + [
        SequenceInLine(sequence=seq) for seq in plasmid_seqs
    ]

    session.add(line)
    session.commit()
    session.refresh(line)
    return _line_ref(line)


@router.patch('/lines/{line_id}', response_model=LineRef)
def patch_line_links(
    line_id: int,
    body: LineUpdate,
    ctx: Annotated[WorkspaceContext, Depends(get_editor_workspace_ctx)],
):
    """Update a line uid, parents, and/or linked alleles/plasmids."""
    current_user, session, workspace_id = ctx
    line = get_line_in_workspace_for_user(session, current_user, workspace_id, line_id, WorkspaceRole.editor)
    workspace_id = line.workspace_id

    if body.uid is not None and body.uid != line.uid:
        existing = session.query(Line).filter_by(uid=body.uid, workspace_id=workspace_id).first()
        if existing:
            raise HTTPException(status_code=409, detail=f"Line UID '{body.uid}' already exists")
        line.uid = body.uid

    if body.allele_ids is not None:
        for sil in list(line.alleles):
            session.delete(sil)
        session.flush()
        for seq_id in body.allele_ids:
            seq = get_sequence_in_workspace_for_user(
                session,
                current_user,
                workspace_id,
                seq_id,
                WorkspaceRole.editor,
                expected_type=SequenceType.allele,
            )
            line.sequences_in_line.append(SequenceInLine(sequence=seq))

    if body.plasmid_ids is not None:
        for sil in list(line.plasmids):
            session.delete(sil)
        session.flush()
        for seq_id in body.plasmid_ids:
            seq = get_sequence_in_workspace_for_user(
                session,
                current_user,
                workspace_id,
                seq_id,
                WorkspaceRole.editor,
                expected_type=SequenceType.plasmid,
            )
            line.sequences_in_line.append(SequenceInLine(sequence=seq))

    if body.parent_ids is not None:
        if line_id in body.parent_ids:
            raise HTTPException(status_code=400, detail='A line cannot be its own parent')
        parents: list[Line] = []
        for parent_id in body.parent_ids:
            parents.append(
                get_line_in_workspace_for_user(
                    session,
                    current_user,
                    workspace_id,
                    parent_id,
                    WorkspaceRole.editor,
                )
            )
        line.parents = parents

    session.commit()
    session.refresh(line)
    return _line_ref(line)


@router.delete('/lines/{line_id}', response_model=DeletedResponse)
def delete_line(
    line_id: int,
    ctx: Annotated[WorkspaceContext, Depends(get_editor_workspace_ctx)],
):
    """Delete a line when it has no children."""
    current_user, session, workspace_id = ctx
    line = get_line_in_workspace_for_user(session, current_user, workspace_id, line_id, WorkspaceRole.editor)
    if line.children:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete line '{line.uid}' because it has children",
        )
    for sil in list(line.sequences_in_line):
        session.delete(sil)

    session.delete(line)
    session.commit()
    return DeletedResponse(deleted=line_id)
