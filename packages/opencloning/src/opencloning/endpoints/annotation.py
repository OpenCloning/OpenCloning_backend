from fastapi import Body, Query
from pydantic import create_model, Field
from typing import Annotated

import pydna
from pydna.primer import Primer as PydnaPrimer

from ..get_router import get_router
from opencloning_linkml.datamodel import (
    TextFileSequence,
    AnnotationSource,
    Primer as PrimerModel,
    PrimerBindingAnnotationReport,
)
from ..dna_functions import (
    read_dsrecord_from_json,
    annotate_with_plannotate as _annotate_with_plannotate,
    annotate_primer_binding_sites as _annotate_primer_binding_sites,
    format_sequence_genbank,
)
from ..primer3_functions import PrimerDesignSettings
from pydna.gateway import find_gateway_sites
from ..app_settings import settings as app_settings

router = get_router()

# Guard against a very short primer producing thousands of features on a large sequence
MAX_PRIMER_BINDING_SITES = 500


@router.post('/annotation/get_gateway_sites', response_model=dict[str, list[str]])
async def get_gateway_sites(
    sequence: TextFileSequence, greedy: bool = Query(False, description='Whether to use the greedy algorithm.')
) -> dict[str, list[str]]:
    """
    Get a dictionary with the names of the gateway sites present in the sequence and their locations as strings.
    """
    dseqr = read_dsrecord_from_json(sequence)
    sites_dict = find_gateway_sites(dseqr, greedy)
    for site in sites_dict:
        sites_dict[site] = [str(loc) for loc in sites_dict[site]]
    return sites_dict


@router.post(
    '/annotate/primer_binding_sites',
    summary='Annotate the binding sites of a set of primers in a sequence',
    response_model=create_model(
        'PrimerBindingSitesResponse',
        sources=(list[AnnotationSource], ...),
        sequences=(list[TextFileSequence], ...),
    ),
)
async def annotate_primer_binding_sites(
    sequence: TextFileSequence,
    source: AnnotationSource,
    primers: Annotated[list[PrimerModel], Field(min_length=1)],
    settings: PrimerDesignSettings = Body(
        description='Settings used to compute the melting temperatures.', default_factory=PrimerDesignSettings
    ),
    minimal_annealing: int = Query(
        14,
        description='The minimal amount of bases that must match between the primer and the sequence, excluding mismatches.',
        ge=1,
    ),
    allowed_mismatches: int = Query(0, description='The number of mismatches allowed', ge=0),
    minimal_tm: float | None = Query(
        None,
        description='If set, binding sites whose melting temperature is below this value (in Celsius) are left out.',
    ),
):
    """
    Add a `primer_bind` feature for every site where any of the primers anneals to the sequence.
    Primers that do not bind anywhere are still included in the annotation report.

    Each site is reported with the melting temperature of the stretch that is bound and that
    of the whole primer, which differ where the primer does not anneal over its entire length.
    """
    input_seqr = read_dsrecord_from_json(sequence)
    pydna_primers = [PydnaPrimer(p.sequence, id=str(p.id), name=p.name) for p in primers]
    primer_lengths = {str(p.id): len(p.sequence) for p in primers}

    seqr, report = _annotate_primer_binding_sites(
        input_seqr,
        pydna_primers,
        minimal_annealing,
        allowed_mismatches,
        MAX_PRIMER_BINDING_SITES,
        settings,
        minimal_tm,
    )

    source.annotation_tool = 'primer_binding_sites'
    source.annotation_tool_version = pydna.__version__
    source.annotation_report = [
        PrimerBindingAnnotationReport(
            primer_id=int(primer.id),
            primer_name=primer.name,
            primer_length=primer_lengths[primer.id],
            start_location=site.start if site is not None else None,
            end_location=site.end if site is not None else None,
            strand=site.strand if site is not None else None,
            matched_length=site.end - site.start if site is not None else None,
            mismatches=site.mismatches if site is not None else None,
            melting_temperature=site.melting_temperature if site is not None else None,
            primer_melting_temperature=site.primer_melting_temperature if site is not None else None,
            gc_content=site.gc_content if site is not None else None,
        )
        for primer, site in report
    ]
    # Only the primers that bind somewhere are recorded as inputs of the source
    bound_primer_ids = sorted({int(primer.id) for primer, site in report if site is not None})
    source.input = [{'sequence': sequence.id}] + [{'sequence': primer_id} for primer_id in bound_primer_ids]
    seqr.name = input_seqr.name + '_primers'

    return {'sources': [source], 'sequences': [format_sequence_genbank(seqr, source.output_name)]}


if app_settings.PLANNOTATE_URL is not None:

    @router.post(
        '/annotate/plannotate',
        summary='Annotate a sequence with Plannotate',
        response_model=create_model(
            'PlannotateResponse',
            sources=(list[AnnotationSource], ...),
            sequences=(list[TextFileSequence], ...),
        ),
    )
    async def annotate_with_plannotate(
        sequence: TextFileSequence,
        source: AnnotationSource,
    ):
        input_seqr = read_dsrecord_from_json(sequence)
        # Make a request submitting sequence as a file:
        seqr, annotations, version = await _annotate_with_plannotate(
            sequence.file_content,
            f'{sequence.id}.gb',
            app_settings.PLANNOTATE_URL + 'annotate',
            app_settings.PLANNOTATE_TIMEOUT,
        )

        source.annotation_report = annotations
        source.annotation_tool = 'plannotate'
        source.annotation_tool_version = version
        seqr.name = input_seqr.name + '_annotated'

        return {'sources': [source], 'sequences': [format_sequence_genbank(seqr, source.output_name)]}
