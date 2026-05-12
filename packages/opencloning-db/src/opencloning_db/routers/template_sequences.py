"""Template sequence endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends

from opencloning_db.apimodels import SequenceRef, TemplateSequenceCreate, sequence_ref
from opencloning_db.models import TemplateSequence
from opencloning_db.workspace_deps import WorkspaceContext, get_editor_workspace_ctx

router = APIRouter(tags=['template_sequences'])


@router.post('/template_sequences', response_model=SequenceRef)
def post_template_sequence(
    ctx: Annotated[WorkspaceContext, Depends(get_editor_workspace_ctx)],
    body: TemplateSequenceCreate,
):
    _, session, _ = ctx.destructure()
    template_sequence = TemplateSequence.from_create(
        name=body.name,
        sequence_type=body.sequence_type,
        ctx=ctx,
    )
    session.add(template_sequence)
    session.commit()
    session.refresh(template_sequence)
    return sequence_ref(template_sequence)
