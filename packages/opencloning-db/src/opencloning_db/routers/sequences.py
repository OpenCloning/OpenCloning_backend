"""Sequence, sequencing files, and cloning strategy endpoints."""

from typing import Annotated, List, TypeVar

from opencloning.dna_functions import read_dsrecord_from_json
import opencloning_linkml.datamodel.models as opencloning_models
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Response
from fastapi import status

from fastapi.responses import FileResponse
from sqlalchemy.orm import selectinload
from sqlalchemy import and_, exists, select, Select
from pathlib import Path

from pydantic import create_model

from opencloning_db.apimodels import (
    CloningStrategyIdMapping,
    CloningStrategyResponse,
    SequenceRef,
    SequenceSearchResult,
    SequenceUpdate,
    SequencingFileRef,
    PrimerRef,
    primer_ref,
    sequence_ref,
)
from opencloning_db.config import Config, get_config
from opencloning_db.db import cloning_strategy_to_db, create_sequencing_file
from opencloning_db.models import (
    InputEntity,
    Primer,
    Sequence,
    SequencingFile,
    Source,
    SequenceType,
    Tag,
    SequenceSample,
    SourceInput,
    WorkspaceRole,
)
from fastapi_pagination import Page
from fastapi_pagination.ext.sqlalchemy import paginate
from opencloning_db.workspace_deps import (
    WorkspaceContext,
    get_editor_workspace_ctx,
    get_sequence_in_workspace_for_user,
    get_viewer_workspace_ctx,
)

from pydna.dseq import Dseq

router = APIRouter(tags=['sequences'])

T = TypeVar('T')


def unique_and_sorted(items: List[T]) -> List[T]:
    return list(sorted(set(items), key=lambda x: x.id))


@router.get('/sequences', response_model=Page[SequenceRef])
def get_sequences(
    ctx: Annotated[WorkspaceContext, Depends(get_viewer_workspace_ctx)],
    tags: list[int] = Query(description='Filter sequences by tag IDs', default_factory=list),
    instantiated: bool | None = Query(description='Filter sequences by whether they are instantiated', default=None),
    sequence_types: list[SequenceType] = Query(description='Filter sequences by type', default_factory=list),
    name: str | None = Query(description='Filter sequences by name (case-insensitive substring match)', default=None),
    uid: str | None = Query(
        description='Filter sequences by sample uid (case-insensitive substring match)', default=None
    ),
    has_uid: bool = Query(description='Filter sequences by whether they have a uid', default=False),
):
    _, session, workspace_id = ctx

    query = (
        select(Sequence)
        .options(
            selectinload(InputEntity.tags),
            selectinload(Sequence.instances),
        )
        .where(Sequence.workspace_id == workspace_id)
    )
    if tags:
        query = query.where(InputEntity.tags.any(and_(Tag.id.in_(tags), Tag.workspace_id == workspace_id)))
    if instantiated is not None:
        query = query.where(Sequence.instances.any() if instantiated else ~Sequence.instances.any())
    if sequence_types is not None and len(sequence_types) > 0:
        query = query.where(Sequence.sequence_type.in_(sequence_types))
    if name is not None:
        query = query.where(Sequence.name.ilike(f"%{name}%"))
    if uid is not None:
        # This creates a boolean filter by including 1 if the sequence has a sample with the given uid
        subq = (
            select(1)
            .select_from(SequenceSample)
            .where(
                SequenceSample.sequence_id == Sequence.id,
                SequenceSample.uid.ilike(f"%{uid}%"),
                SequenceSample.uid_workspace_id == workspace_id,
            )
        )
        query = query.where(exists(subq))
    if has_uid is True:
        subq = (
            select(1)
            .select_from(SequenceSample)
            .where(
                SequenceSample.sequence_id == Sequence.id,
                SequenceSample.uid.isnot(None),
                SequenceSample.uid_workspace_id == workspace_id,
            )
        )
        query = query.where(exists(subq))
    return paginate(session, query)


@router.get('/sequences/{sequence_id}', response_model=SequenceRef)
def get_sequence(
    sequence_id: int,
    ctx: Annotated[WorkspaceContext, Depends(get_viewer_workspace_ctx)],
):
    current_user, session, workspace_id = ctx
    db_sequence = get_sequence_in_workspace_for_user(
        session, current_user, workspace_id, sequence_id, WorkspaceRole.viewer
    )
    return sequence_ref(db_sequence)


@router.patch('/sequences/{sequence_id}', response_model=SequenceRef)
def patch_sequence(
    sequence_id: int,
    body: SequenceUpdate,
    ctx: Annotated[WorkspaceContext, Depends(get_editor_workspace_ctx)],
):
    """Update the sequence name and/or sequence_type."""
    current_user, session, workspace_id = ctx
    db_sequence = get_sequence_in_workspace_for_user(
        session, current_user, workspace_id, sequence_id, WorkspaceRole.editor
    )

    if body.name is not None:
        if body.name == '':
            raise HTTPException(status_code=400, detail='Name cannot be an empty string')
        db_sequence.name = body.name

    if body.sequence_type is not None:
        # Enforce: circular sequences can only be typed as plasmids.
        seq_record = read_dsrecord_from_json(db_sequence.to_pydantic_sequence())
        if seq_record.circular and body.sequence_type != SequenceType.plasmid:
            raise HTTPException(
                status_code=400,
                detail="Circular sequences can only have sequence_type 'plasmid'",
            )
        db_sequence.sequence_type = body.sequence_type

    session.commit()
    session.refresh(db_sequence)
    return sequence_ref(db_sequence)


@router.get('/sequences/by-uid/{uid}', response_model=SequenceRef)
def get_sequence_by_uid(
    uid: str,
    ctx: Annotated[WorkspaceContext, Depends(get_viewer_workspace_ctx)],
):
    """
    Look up the unique sequence associated with a given sample UID.
    Returns 404 if no sample/sequence exists for that UID.
    """
    _, session, workspace_id = ctx
    stmt = (
        select(Sequence)
        .where(Sequence.workspace_id == workspace_id)
        .join(SequenceSample, SequenceSample.sequence_id == Sequence.id)
        .where(
            SequenceSample.uid == uid,
            SequenceSample.uid_workspace_id == workspace_id,
        )
        .options(
            selectinload(InputEntity.tags),
            selectinload(Sequence.instances),
        )
    )
    db_sequence = session.scalar(stmt)
    if db_sequence is None:
        raise HTTPException(status_code=404, detail='Sequence not found for UID')
    return sequence_ref(db_sequence)


def _seguid_query(seguid: str, workspace_id: int) -> Select[Sequence]:
    return (
        select(Sequence)
        .where(
            Sequence.seguid == seguid,
            Sequence.workspace_id == workspace_id,
        )
        .options(
            selectinload(InputEntity.tags),
            selectinload(Sequence.instances),
        )
    )


@router.get('/sequences/by-seguid/{seguid}', response_model=list[SequenceRef])
def get_sequences_by_seguid(
    seguid: str,
    ctx: Annotated[WorkspaceContext, Depends(get_viewer_workspace_ctx)],
):
    """
    Look up all sequences with the given SEGUID.
    Returns an empty list if none are found.
    """
    _, session, workspace_id = ctx
    stmt = _seguid_query(seguid, workspace_id)
    return [sequence_ref(seq) for seq in session.scalars(stmt).all()]


@router.get('/sequences/{sequence_id}/text_file_sequence', response_model=opencloning_models.TextFileSequence)
def get_text_file_sequence(
    sequence_id: int,
    ctx: Annotated[WorkspaceContext, Depends(get_viewer_workspace_ctx)],
):
    current_user, session, workspace_id = ctx
    db_sequence = get_sequence_in_workspace_for_user(
        session, current_user, workspace_id, sequence_id, WorkspaceRole.viewer
    )
    return db_sequence.to_pydantic_sequence()


@router.get('/sequences/{sequence_id}/cloning_strategy', response_model=opencloning_models.CloningStrategy)
def get_cloning_strategy(
    sequence_id: int,
    ctx: Annotated[WorkspaceContext, Depends(get_viewer_workspace_ctx)],
):
    current_user, session, workspace_id = ctx
    db_sequence = get_sequence_in_workspace_for_user(
        session, current_user, workspace_id, sequence_id, WorkspaceRole.viewer
    )
    parent_source = db_sequence.output_of_source
    parent_sequences = [
        source_input.input_entity
        for source_input in parent_source.input
        if isinstance(source_input.input_entity, Sequence)
        and source_input.input_entity.workspace_id == db_sequence.workspace_id  # TODO: Maybe remove?
    ]
    primers: list[Primer] = [
        source_input.input_entity
        for source_input in parent_source.input
        if isinstance(source_input.input_entity, Primer)
        and source_input.input_entity.workspace_id == db_sequence.workspace_id  # TODO: Maybe remove?
    ]

    grandparent_sources: list[Source] = []
    grandparent_sources += [s.output_of_source for s in parent_sequences]

    all_sequences = [db_sequence] + parent_sequences
    all_sources = [parent_source] + grandparent_sources

    exported_sequences = [seq.to_pydantic_sequence() for seq in unique_and_sorted(all_sequences)]
    exported_primers = [primer.to_pydantic_primer() for primer in unique_and_sorted(primers)]
    exported_sources = [source.to_pydantic_source() for source in unique_and_sorted(all_sources)]

    return opencloning_models.CloningStrategy(
        sequences=exported_sequences,
        sources=exported_sources,
        primers=exported_primers,
        description='',
        files=[],
    )


@router.get('/sequences/{sequence_id}/children', response_model=list[SequenceRef])
def get_sequence_children(
    sequence_id: int,
    ctx: Annotated[WorkspaceContext, Depends(get_viewer_workspace_ctx)],
):
    current_user, session, workspace_id = ctx
    db_sequence = get_sequence_in_workspace_for_user(
        session, current_user, workspace_id, sequence_id, WorkspaceRole.viewer
    )
    return [sequence_ref(s.source.output_sequence) for s in db_sequence.source_inputs]


@router.get(
    '/sequences/{sequence_id}/primers',
    response_model=create_model(
        'SequencePrimers',
        templates=list[PrimerRef],
        products=list[PrimerRef],
    ),
)
def get_sequence_primers(
    sequence_id: int,
    ctx: Annotated[WorkspaceContext, Depends(get_viewer_workspace_ctx)],
):
    """Get primers linked to a sequence (as template input or product output)."""
    current_user, session, workspace_id = ctx
    db_sequence = get_sequence_in_workspace_for_user(
        session, current_user, workspace_id, sequence_id, WorkspaceRole.viewer
    )
    workspace_id = db_sequence.workspace_id

    # Sources where this sequence was an input (i.e. this sequence acted as a "template")
    template_source_ids = select(SourceInput.source_id).where(SourceInput.input_entity_id == sequence_id)
    template_primers_stmt = (
        select(Primer)
        .options(selectinload(InputEntity.tags))
        .join(SourceInput, SourceInput.input_entity_id == Primer.id)
        .where(
            SourceInput.source_id.in_(template_source_ids),
            Primer.workspace_id == workspace_id,
        )
        .distinct()
    )

    # Sources where this sequence was the output (i.e. this sequence acted as a "product")
    product_source_ids = select(Source.id).where(Source.id == sequence_id)
    product_primers_stmt = (
        select(Primer)
        .options(selectinload(InputEntity.tags))
        .join(SourceInput, SourceInput.input_entity_id == Primer.id)
        .where(
            SourceInput.source_id.in_(product_source_ids),
            Primer.workspace_id == workspace_id,
        )
        .distinct()
    )

    templates = session.execute(template_primers_stmt).scalars().all()
    products = session.execute(product_primers_stmt).scalars().all()

    return {
        'templates': [primer_ref(p) for p in sorted(templates, key=lambda p: p.id)],
        'products': [primer_ref(p) for p in sorted(products, key=lambda p: p.id)],
    }


@router.get('/sequences/{sequence_id}/sequencing_files', response_model=List[SequencingFileRef])
def get_sequence_sequencing_files(
    sequence_id: int,
    ctx: Annotated[WorkspaceContext, Depends(get_viewer_workspace_ctx)],
):
    """List all sequencing files linked to a sequence."""
    current_user, session, workspace_id = ctx
    db_sequence = get_sequence_in_workspace_for_user(
        session, current_user, workspace_id, sequence_id, WorkspaceRole.viewer
    )
    return [SequencingFileRef(id=f.id, original_name=f.original_name) for f in db_sequence.sequencing_files]


@router.post('/sequences/{sequence_id}/sequencing_files', response_model=List[SequencingFileRef])
async def post_sequence_sequencing_files(
    sequence_id: int,
    ctx: Annotated[WorkspaceContext, Depends(get_editor_workspace_ctx)],
    files: List[UploadFile] = File(...),
):
    """Upload one or more sequencing files and link them to a sequence."""
    current_user, session, workspace_id = ctx
    db_sequence = get_sequence_in_workspace_for_user(
        session, current_user, workspace_id, sequence_id, WorkspaceRole.editor
    )

    created = []
    for upload in files:
        content = await upload.read()
        sf = create_sequencing_file(
            sequence=db_sequence,
            file_content=content,
            original_name=upload.filename or 'unnamed',
        )
        session.add(sf)
        session.flush()
        created.append(SequencingFileRef(id=sf.id, original_name=sf.original_name))

    session.commit()
    return created


@router.delete('/sequences/{sequence_id}/sequencing_files/{file_id}', status_code=status.HTTP_204_NO_CONTENT)
def delete_sequence_sequencing_file(
    sequence_id: int,
    file_id: int,
    ctx: Annotated[WorkspaceContext, Depends(get_editor_workspace_ctx)],
):
    current_user, session, workspace_id = ctx
    get_sequence_in_workspace_for_user(session, current_user, workspace_id, sequence_id, WorkspaceRole.editor)
    db_file = session.scalar(
        select(SequencingFile).where(SequencingFile.id == file_id, SequencingFile.sequence_id == sequence_id)
    )
    if db_file is None:
        raise HTTPException(status_code=404, detail='Sequencing file not found')
    session.delete(db_file)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get('/sequencing_files/{file_id}/download')
def download_sequencing_file(
    file_id: int,
    ctx: Annotated[WorkspaceContext, Depends(get_viewer_workspace_ctx)],
    config: Annotated[Config, Depends(get_config)],
):
    """Download a sequencing file by ID."""
    current_user, session, workspace_id = ctx
    db_file = session.get(SequencingFile, file_id)
    if db_file is None:
        raise HTTPException(status_code=404, detail='Sequencing file not found')
    get_sequence_in_workspace_for_user(session, current_user, workspace_id, db_file.sequence_id, WorkspaceRole.viewer)
    storage_path = db_file.storage_path
    original_name = db_file.original_name

    file_path = Path(config.sequencing_files_dir) / storage_path
    if not file_path.exists():
        raise HTTPException(status_code=404, detail='File not found on disk')

    return FileResponse(
        path=str(file_path),
        filename=original_name,
        media_type='application/octet-stream',
    )


@router.post('/sequences', response_model=CloningStrategyResponse)
def post_cloning_strategy(
    ctx: Annotated[WorkspaceContext, Depends(get_editor_workspace_ctx)],
    cloning_strategy: opencloning_models.CloningStrategy,
):
    _, session, workspace_id = ctx
    sequences, id_mappings = cloning_strategy_to_db(cloning_strategy, session, workspace_id)
    session.flush()
    root_sequence = next((s for s in sequences if len(s.source_inputs) == 0))
    session.refresh(root_sequence)
    session.commit()
    formatted_mappings = [
        CloningStrategyIdMapping(localId=k, databaseId=v) for k, v in id_mappings.items() if v is not None
    ]
    return CloningStrategyResponse(id=root_sequence.id, mappings=formatted_mappings)


def _search_rotation(seqr: Dseq, query_seqr: Dseq) -> tuple[int, bool]:
    if len(seqr) != len(query_seqr) or not seqr.circular or not query_seqr.circular:
        raise ValueError('Sequences must be the same length and circular')

    reference_seq = seqr.upper() + seqr.upper()
    query_seqr = query_seqr.upper()
    result_fwd = reference_seq.find(query_seqr)
    if result_fwd != -1:
        return result_fwd, False
    result_rev = reference_seq.find(query_seqr.reverse_complement())
    if result_rev != -1:
        return result_rev, True
    raise ValueError('Query sequence not found in reference sequence')


@router.post('/sequences/search', response_model=list[SequenceSearchResult])
def search_sequences(
    ctx: Annotated[WorkspaceContext, Depends(get_viewer_workspace_ctx)],
    query: opencloning_models.TextFileSequence,
):
    query_dseq = read_dsrecord_from_json(query).seq
    seguid = query_dseq.seguid()
    current_user, session, workspace_id = ctx
    output = []
    results = session.scalars(_seguid_query(seguid, workspace_id))
    for db_seq in results:
        db_seq: Sequence
        db_dseq = read_dsrecord_from_json(db_seq.to_pydantic_sequence()).seq
        if db_dseq.circular:
            shift, reverse_complemented = _search_rotation(db_dseq, query_dseq)
            output.append(
                SequenceSearchResult(
                    sequence_ref=sequence_ref(db_seq),
                    sequence=db_seq.to_pydantic_sequence(),
                    shift=shift,
                    reverse_complemented=reverse_complemented,
                )
            )
        else:
            output.append(
                SequenceSearchResult(
                    sequence_ref=sequence_ref(db_seq),
                    sequence=db_seq.to_pydantic_sequence(),
                    shift=0,
                    reverse_complemented=db_dseq != query_dseq,
                )
            )
    return output
