"""
Database engine and conversion logic (Pydantic <-> ORM).
"""

import os
from typing import List

import opencloning_linkml.datamodel.models as opencloning_models
from pydna.dseqrecord import Dseqrecord
import pydna.opencloning_models as pydna_opencloning_models
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from opencloning_db.apimodels import (
    CloningStrategySyncResult,
    PrimerDatabaseIdMismatch,
    SequenceDatabaseIdMismatch,
)
from opencloning_db.config import Config, set_config
from opencloning_db.context import ReadContext, WriteContext
from opencloning_db.models import (
    Primer,
    Sequence,
    Source,
    SequencingFile,
    Tag,
    WorkspaceRole,
)
from opencloning_db.storage import get_storage, set_storage
from opencloning_db.utils import guess_sequence_type
from opencloning_db.models import require_real_sequence

_engine = None
_bound_database_url: str | None = None


def reset_runtime_state(config: Config | None = None) -> None:
    global _engine, _bound_database_url
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _bound_database_url = None
    set_storage(None)
    set_config(config)


def get_engine(config: Config):
    """Return the DB engine; rebuild when ``config.database_url`` changes."""
    global _engine, _bound_database_url
    url = config.database_url
    if _engine is None or _bound_database_url != url:
        _engine = create_engine(url)
        _bound_database_url = url
    return _engine


def create_sequencing_file(
    sequence: 'Sequence',
    file_content: bytes,
    original_name: str,
    content_type: str | None = None,
) -> SequencingFile:
    """Create SequencingFile; write content to a unique object key."""
    ext = os.path.splitext(original_name)[1]
    storage = get_storage()
    storage_filename = storage.new_sequencing_key(ext)
    storage.write_bytes(storage_filename, file_content, content_type=content_type or 'application/octet-stream')
    return SequencingFile(
        sequence=sequence,
        original_name=original_name,
        storage_path=storage_filename,
    )


def _source_order(cloning_strategy: opencloning_models.CloningStrategy) -> List[int]:
    """Return source ids in topological order (dependencies first) for single_parent compatibility."""
    source_ids = {s.id for s in cloning_strategy.sources}
    deps = {}
    for src in cloning_strategy.sources:
        input_seq_ids = {item.sequence for item in (src.input or [])}
        deps[src.id] = {sid for sid in input_seq_ids if sid in source_ids}

    order = []
    visited = set()

    def visit(sid: int) -> None:
        if sid in visited:
            return
        visited.add(sid)
        for dep in deps.get(sid, ()):
            visit(dep)
        order.append(sid)

    for src in cloning_strategy.sources:
        visit(src.id)
    return list(order)


def dseqrecord_to_db(
    dseqrecord: Dseqrecord,
    session: Session,
    *,
    ctx: WriteContext,
) -> Sequence:
    """Persist *dseqrecord* via ``from_dseqrecords`` → ``cloning_strategy_to_db``.

    Intended for single-output strategies (one sequence row). Returns that ``Sequence``.
    """
    cs = pydna_opencloning_models.CloningStrategy.from_dseqrecords([dseqrecord])
    if len(cs.sequences) != 1:
        raise ValueError(f"dseqrecord_to_db expects exactly one sequence in the strategy; got {len(cs.sequences)}")
    sequences, _ = cloning_strategy_to_db(cs, session, ctx=ctx)
    return sequences[0]


def _normalize_primer_sequence(sequence: str | None) -> str:
    return (sequence or '').lower()


def get_db_primers_from_database_ids(
    session: Session,
    workspace_id: int,
    database_ids: set[int],
) -> dict[int, Primer]:
    if len(database_ids) == 0:
        return {}
    return {
        primer.id: primer
        for primer in session.scalars(
            select(Primer).where(
                Primer.workspace_id == workspace_id,
                Primer.id.in_(database_ids),
            )
        ).all()
    }


def get_db_primers_grouped_by_sequence(
    session: Session,
    workspace_id: int,
    sequences: set[str],
) -> dict[str, list[Primer]]:
    if len(sequences) == 0:
        return {}
    grouped: dict[str, list[Primer]] = {}
    for primer in session.scalars(
        select(Primer).where(
            Primer.workspace_id == workspace_id,
            func.lower(Primer.sequence).in_(sequences),
        )
    ).all():
        grouped.setdefault(_normalize_primer_sequence(primer.sequence), []).append(primer)
    return grouped


def get_primer_db_mismatch(
    primer: opencloning_models.Primer,
    existing_primer: Primer | None,
    normalized_sequence: str,
) -> PrimerDatabaseIdMismatch | None:
    provided_database_id = primer.database_id
    if provided_database_id is None:
        return None

    if existing_primer is None:
        return PrimerDatabaseIdMismatch(
            primer_id=primer.id,
            provided_database_id=provided_database_id,
            kind='not_found',
        )

    if _normalize_primer_sequence(existing_primer.sequence) != normalized_sequence:
        return PrimerDatabaseIdMismatch(
            primer_id=primer.id,
            provided_database_id=provided_database_id,
            kind='sequence_mismatch',
        )

    return None


def _verify_incoming_primer_database_ids(
    primers: list[opencloning_models.Primer],
    existing_primers_by_id: dict[int, Primer],
) -> tuple[list[PrimerDatabaseIdMismatch], dict[int, str], set[str]]:

    mismatches: list[PrimerDatabaseIdMismatch] = []
    primer_sequences: dict[int, str] = {}
    sequences_needing_match: set[str] = set()

    for primer in primers:
        normalized_sequence = _normalize_primer_sequence(primer.sequence)
        primer_sequences[primer.id] = normalized_sequence

        if primer.database_id is None:
            sequences_needing_match.add(normalized_sequence)
            continue

        mismatch = get_primer_db_mismatch(
            primer,
            existing_primers_by_id.get(primer.database_id),
            normalized_sequence,
        )
        if mismatch is not None:
            mismatches.append(mismatch)
            primer.database_id = None
            sequences_needing_match.add(normalized_sequence)

    return mismatches, primer_sequences, sequences_needing_match


def _link_primers_by_unique_sequence_match(
    primers: list[opencloning_models.Primer],
    primer_sequences: dict[int, str],
    existing_primers_by_sequence: dict[str, list[Primer]],
) -> None:
    for primer in primers:
        if primer.database_id is not None:
            continue
        matches = existing_primers_by_sequence.get(primer_sequences[primer.id], [])
        if len(matches) == 1:
            primer.database_id = matches[0].id


def _sync_primers_with_db(
    primers: list[opencloning_models.Primer],
    session: Session,
    workspace_id: int,
) -> list[PrimerDatabaseIdMismatch]:
    if len(primers) == 0:
        return []

    provided_database_ids = {primer.database_id for primer in primers if primer.database_id is not None}
    existing_primers_by_id = get_db_primers_from_database_ids(session, workspace_id, provided_database_ids)
    mismatches, primer_sequences, sequences_needing_match = _verify_incoming_primer_database_ids(
        primers, existing_primers_by_id
    )

    if len(sequences_needing_match) > 0:
        existing_primers_by_sequence = get_db_primers_grouped_by_sequence(
            session, workspace_id, sequences_needing_match
        )
        _link_primers_by_unique_sequence_match(primers, primer_sequences, existing_primers_by_sequence)

    return mismatches


def get_db_sequences_from_database_ids(
    session: Session,
    workspace_id: int,
    database_ids: set[int],
) -> dict[int, Sequence]:
    if len(database_ids) == 0:
        return {}
    return {
        sequence.id: sequence
        for sequence in session.scalars(
            select(Sequence).where(
                Sequence.workspace_id == workspace_id,
                Sequence.id.in_(database_ids),
            )
        ).all()
    }


def get_db_sequences_grouped_by_seguid(
    session: Session,
    workspace_id: int,
    seguids: set[str],
) -> dict[str, list[Sequence]]:
    if len(seguids) == 0:
        return {}
    grouped: dict[str, list[Sequence]] = {}
    for sequence in session.scalars(
        select(Sequence).where(
            Sequence.workspace_id == workspace_id,
            Sequence.seguid.in_(seguids),
        )
    ).all():
        grouped.setdefault(sequence.seguid, []).append(sequence)
    return grouped


def _clear_dseqrecord_database_id(dseqr: Dseqrecord) -> None:
    assert dseqr.source is not None

    if isinstance(dseqr.source, pydna_opencloning_models.DatabaseSource):
        # This assignment is because DatabaseSource cannot have a database_id that is None
        dseqr.source = None
    else:
        dseqr.source.database_id = None


def _link_dseqrecord_to_database(dseqr: Dseqrecord, database_id: int) -> None:
    dseqr.source = pydna_opencloning_models.DatabaseSource(database_id=database_id, input=[])


def get_sequence_db_mismatch(
    *,
    sequence_id: int,
    provided_database_id: int,
    existing_sequence: Sequence | None,
    seguid: str,
) -> SequenceDatabaseIdMismatch | None:
    if existing_sequence is None:
        return SequenceDatabaseIdMismatch(
            sequence_id=sequence_id,
            provided_database_id=provided_database_id,
            kind='not_found',
        )

    if existing_sequence.seguid != seguid:
        return SequenceDatabaseIdMismatch(
            sequence_id=sequence_id,
            provided_database_id=provided_database_id,
            kind='seguid_mismatch',
        )

    return None


def _collect_dseqrecord_graph_lookups(
    dseqr: Dseqrecord,
    seguids: set[str],
    database_ids: set[int],
) -> None:
    """Collect SEGUIDs and database IDs from a Dseqrecord graph."""
    seguids.add(dseqr.seq.seguid())
    if dseqr.source is None:
        return
    if dseqr.source.database_id is not None:
        database_ids.add(dseqr.source.database_id)

    for source_input in dseqr.source.input:
        child = source_input.sequence
        if isinstance(child, Dseqrecord):
            _collect_dseqrecord_graph_lookups(child, seguids, database_ids)


def _replace_sequence_source_if_exists_in_db(
    dseqr: Dseqrecord,
    existing_sequences_by_id: dict[int, Sequence],
    existing_sequences_by_seguid: dict[str, list[Sequence]],
    mismatches: list[SequenceDatabaseIdMismatch],
    visited: set[int],
) -> None:
    """Recursively navigate a Dseqrecord history graph up to the first ancestor that exists in the database.
    If it exists, replace the source with a DatabaseSource, otherwise keep going up the graph.
    """
    local_id = pydna_opencloning_models.get_id(dseqr)
    if local_id in visited:
        return
    visited.add(local_id)

    seguid = dseqr.seq.seguid()

    # "provided" because it comes from the cloning strategy, and might not be correct
    provided_database_id = None if dseqr.source is None else dseqr.source.database_id

    if provided_database_id is not None:
        mismatch = get_sequence_db_mismatch(
            sequence_id=local_id,
            provided_database_id=provided_database_id,
            existing_sequence=existing_sequences_by_id.get(provided_database_id),
            seguid=seguid,
        )
        if mismatch is None:
            if not isinstance(dseqr.source, pydna_opencloning_models.DatabaseSource):
                _link_dseqrecord_to_database(dseqr, provided_database_id)
            return

        mismatches.append(mismatch)
        _clear_dseqrecord_database_id(dseqr)

    matches = existing_sequences_by_seguid.get(seguid, [])
    if len(matches) > 0:
        db_sequence = min(matches, key=lambda sequence: sequence.id)
        _link_dseqrecord_to_database(dseqr, db_sequence.id)
        return

    if dseqr.source is None:
        return

    for source_input in dseqr.source.input:
        child = source_input.sequence
        if isinstance(child, Dseqrecord):
            _replace_sequence_source_if_exists_in_db(
                child,
                existing_sequences_by_id,
                existing_sequences_by_seguid,
                mismatches,
                visited,
            )


def _replace_sequences_file_content_if_exists_in_db(
    synced_strategy: pydna_opencloning_models.CloningStrategy,
    existing_sequences_by_id: dict[int, Sequence],
    existing_sequences_by_seguid: dict[str, list[Sequence]],
) -> None:
    all_db_sequences = list(existing_sequences_by_id.values()) + sum(list(existing_sequences_by_seguid.values()), [])
    for source in synced_strategy.sources:
        if source.database_id is not None:
            sequence = next((s for s in synced_strategy.sequences if s.id == source.id))
            db_sequence = next((s for s in all_db_sequences if s.id == source.database_id))
            sequence.file_content = db_sequence.to_pydantic_sequence().file_content


def _sync_sequences_via_dseqrecords(
    pydna_strategy: pydna_opencloning_models.CloningStrategy,
    session: Session,
    workspace_id: int,
) -> tuple[pydna_opencloning_models.CloningStrategy, list[SequenceDatabaseIdMismatch]]:
    terminals = pydna_strategy.to_dseqrecords()
    seguids: set[str] = set()
    database_ids: set[int] = set()
    for terminal in terminals:
        _collect_dseqrecord_graph_lookups(terminal, seguids, database_ids)

    existing_sequences_by_id = get_db_sequences_from_database_ids(session, workspace_id, database_ids)
    existing_sequences_by_seguid = get_db_sequences_grouped_by_seguid(session, workspace_id, seguids)

    mismatches: list[SequenceDatabaseIdMismatch] = []
    visited: set[int] = set()
    for terminal in terminals:
        _replace_sequence_source_if_exists_in_db(
            terminal,
            existing_sequences_by_id,
            existing_sequences_by_seguid,
            mismatches,
            visited,
        )

    synced_strategy = pydna_opencloning_models.CloningStrategy.from_dseqrecords(
        terminals,
        pydna_strategy.description or '',
    )

    # Finally, for sequences that do exist in the database, replace their sequence.file_content with that of the db.
    _replace_sequences_file_content_if_exists_in_db(
        synced_strategy, existing_sequences_by_id, existing_sequences_by_seguid
    )

    # Then normalize
    try:
        synced_strategy = synced_strategy.normalize()
    except ValueError as e:  # pragma: no cover # This should never happen, as input is validated before syncing
        raise ValueError(f"Error normalizing cloning strategy: {e}") from e

    return synced_strategy, mismatches


def sync_cloning_strategy_with_db(
    cloning_strategy: opencloning_models.CloningStrategy,
    session: Session,
    *,
    ctx: ReadContext,
) -> CloningStrategySyncResult:
    """
    Sync a cloning strategy against existing workspace entities. It assumes that is
    validated before syncing.

    For primers:
    - If ``database_id`` is set, verify it exists in the workspace and matches sequence
      (case-insensitive). On failure, record a mismatch warning and clear ``database_id``.
    - Then match remaining primers by sequence; if exactly one workspace primer matches,
      set ``database_id`` to that primer.

    For sequences (via pydna graph):
    - Rebuild terminal ``Dseqrecord`` objects with ``to_dseqrecords()``.
    - Validate or resolve ``database_id`` by SEGUID; on match, replace source with
      ``DatabaseSource`` (dropping parent provenance).
    - Rebuild the strategy with ``from_dseqrecords()``.
    """
    synced_primers = [
        opencloning_models.Primer.model_validate(primer.model_dump(mode='json'))
        for primer in (cloning_strategy.primers or [])
    ]
    primer_mismatches = _sync_primers_with_db(synced_primers, session, ctx.workspace_id)
    pydna_strategy = pydna_opencloning_models.CloningStrategy.model_validate(cloning_strategy.model_dump(mode='json'))

    with pydna_opencloning_models.id_mode(use_python_internal_id=False):
        pydna_strategy, sequence_mismatches = _sync_sequences_via_dseqrecords(
            pydna_strategy,
            session,
            ctx.workspace_id,
        )

        linkml_strategy = opencloning_models.CloningStrategy.model_validate(pydna_strategy.model_dump(mode='json'))
    # Primers are added here, which means that even if they are not used in the cloning, they will be added.
    # If they are already in the db, they are skipped anyway.
    linkml_strategy.primers = synced_primers
    all_sequences_are_in_db = all(source.database_id is not None for source in linkml_strategy.sources)
    all_primers_are_in_db = all(primer.database_id is not None for primer in linkml_strategy.primers)

    return CloningStrategySyncResult(
        cloning_strategy=linkml_strategy,
        primer_database_id_mismatches=primer_mismatches,
        sequence_database_id_mismatches=sequence_mismatches,
        already_synced=all_sequences_are_in_db and all_primers_are_in_db,
    )


def cloning_strategy_to_db(
    cloning_strategy: opencloning_models.CloningStrategy,
    session: Session,
    *,
    ctx: WriteContext,
    tags: list[Tag] | None = None,
) -> tuple[list[Sequence], dict[int, int]]:
    from opencloning_db.workspace_deps import get_sequence_in_workspace_for_user

    sequences = []
    entity_mapping = {}  # Combined mapping for sequences and primers (by id)

    for sequence in cloning_strategy.sequences:
        # New model: source.id == output sequence id
        parent_source = next((s for s in cloning_strategy.sources if s.id == sequence.id), None)
        if parent_source is None:
            raise ValueError(f"No source produces sequence {sequence.id}")
        if parent_source.database_id is None:
            db_sequence = Sequence.from_pydantic_sequence(sequence, ctx=ctx)
            db_sequence.sequence_type = guess_sequence_type(sequence, parent_source)
            if tags:
                db_sequence.tags.extend(tags)
        else:
            db_sequence = get_sequence_in_workspace_for_user(
                session, ctx.user, ctx.workspace_id, parent_source.database_id, WorkspaceRole.editor
            )
            require_real_sequence(
                db_sequence,
                detail=f'Parent sequence {parent_source.database_id} is a template. Please contact support.',
                status_code=400,
            )
        sequences.append(db_sequence)
        entity_mapping[sequence.id] = db_sequence

    for primer in cloning_strategy.primers or []:
        db_primer = (
            Primer.from_pydantic(primer, ctx=ctx)
            if primer.database_id is None
            else session.get(Primer, primer.database_id)
        )
        entity_mapping[primer.id] = db_primer

    # Add primers first (no output_of_source); flush so they're persisted before any source references them
    for primer in cloning_strategy.primers or []:
        if primer.database_id is None:
            db_primer = entity_mapping[primer.id]
            if tags:
                db_primer.tags.extend(tags)
            session.add(db_primer)
    session.flush()

    # Process sources in topological order, add+flush each to satisfy single_parent
    source_by_id = {s.id: s for s in cloning_strategy.sources}
    for source_id in _source_order(cloning_strategy):
        source = source_by_id[source_id]
        if source.database_id is not None:
            continue
        output_sequence = entity_mapping[source.id]
        Source.from_pydantic(source, output_sequence, entity_mapping)
        session.add(output_sequence)
        session.flush()

    id_mappings = {k: v.id for k, v in entity_mapping.items()}
    return sequences, id_mappings
