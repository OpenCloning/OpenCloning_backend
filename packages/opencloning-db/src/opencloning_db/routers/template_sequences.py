"""Template sequence endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError

from opencloning_db.apimodels import SequenceRef, TemplateSequenceCreate, sequence_ref
from opencloning_db.models import TemplateSequence, assert_template_sequence_name_available
from opencloning_db.workspace_deps import WorkspaceContext, get_editor_workspace_ctx

router = APIRouter(tags=['template_sequences'])


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
