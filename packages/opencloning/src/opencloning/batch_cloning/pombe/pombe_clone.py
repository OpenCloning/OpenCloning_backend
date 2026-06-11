import json
import os
from opencloning.dna_utils import trim_location
from pydna.dseqrecord import Dseqrecord
from pydna.assembly2 import homologous_recombination_integration, pcr_assembly
from opencloning.ncbi_requests import get_annotations_from_query, get_genome_region_from_annotation
from pydna.primer import Primer
from pydna.opencloning_models import CloningStrategy
from pydna.utils import location_boundaries
from typing import Literal
from opencloning.primer_design import primer_in_region
from .pombe_naming import allele_name, integration_primer_name
from Bio.SeqFeature import SeqFeature


def get_homology_arms(locus: Dseqrecord, feature: SeqFeature, cloning_type: str) -> tuple[str, str]:
    if cloning_type == 'gene_deletion':
        start, end = (int(i) for i in location_boundaries(feature.location))
        left_homology_arm = str(locus.seq[start - 80 : start]).lower()
        right_homology_arm = str(locus.seq[end : end + 80].reverse_complement()).lower()
    elif cloning_type == 'gene_cterm_tagging':
        feature.location = trim_location(feature.location, 3, from_end=True)
        start, end = (int(i) for i in location_boundaries(feature.location))
        left_homology_arm = str(locus.seq[end - 80 : end]).lower()
        right_homology_arm = str(locus.seq[end : end + 80].reverse_complement()).lower()
    elif cloning_type in ('promoter_not_tag', 'promoter_with_tag'):
        start, end = (int(i) for i in location_boundaries(feature.location))
        left_homology_arm = str(locus.seq[start - 80 : start]).lower()
        right_homology_arm = str(locus.seq[start : start + 80].reverse_complement()).lower()
    else:
        raise ValueError(f'Unsupported cloning type: {cloning_type}')

    return left_homology_arm, right_homology_arm


def get_checking_primers(
    locus: Dseqrecord, feature: SeqFeature, gene: str, cloning_type: str, region_length: int = 200
) -> tuple[Primer, Primer]:
    start, end = (int(i) for i in location_boundaries(feature.location))

    def get_upstream_primer():
        padding = 200
        primer = primer_in_region(locus[(start - padding - region_length) : (start - padding)], forward=True)
        primer.name = f'{gene}_check_upstream_fwd'
        return primer

    def get_downstream_primer():
        padding = 200
        primer = primer_in_region(locus[(end + padding) : (end + padding + region_length)], forward=False)
        primer.name = f'{gene}_check_downstream_rvs'
        return primer

    def get_inside_forward_primer():
        padding = 200
        primer = primer_in_region(locus[(end - padding - region_length) : (end - padding)], forward=True)
        primer.name = f'{gene}_check_inside_fwd'
        return primer

    def get_inside_reverse_primer():
        padding = 200
        primer = primer_in_region(locus[(start + padding) : (start + padding + region_length)], forward=False)
        primer.name = f'{gene}_check_inside_rvs'
        return primer

    if cloning_type == 'gene_deletion':
        fwd = get_upstream_primer()
        rvs = get_downstream_primer()
    elif cloning_type == 'gene_cterm_tagging':
        fwd = get_inside_forward_primer()
        rvs = get_downstream_primer()
    elif cloning_type in ('promoter_not_tag', 'promoter_with_tag'):
        fwd = get_upstream_primer()
        rvs = get_inside_reverse_primer()
    else:
        raise ValueError(f'Unsupported cloning type: {cloning_type}')

    return fwd, rvs


async def main(
    gene: str,
    assembly_accession: str,
    output_dir: str,
    plasmid: Dseqrecord,
    common_primers: list[Primer],
    integration_binding_forward: str,
    integration_binding_reverse: str,
    cloning_type: Literal['gene_deletion', 'gene_cterm_tagging', 'promoter_not_tag', 'promoter_with_tag'],
):
    print(f"\033[92mCloning {gene}\033[0m")
    # Parse primers =================================================================================
    # Primers have to be: clone_fwd, clone_rvs, check_fwd, check_rvs

    # Get genome region =====================================================================
    annotations = await get_annotations_from_query(gene, assembly_accession)
    if len(annotations) == 0:
        raise ValueError(f'No annotations found for {gene}')

    annotations = [a for a in annotations if gene.upper() in a['locus_tag'].upper()]
    if len(annotations) == 0:
        raise ValueError(f'No right annotation found for {gene}')
    if len(annotations) > 1:
        raise ValueError(f'Multiple annotations found for {gene}')

    annotation = annotations[0]
    if annotation['gene_type'] != 'protein-coding':
        raise ValueError(f'{gene} is not a protein-coding gene')
    if 'gene_id' not in annotation or not annotation['gene_id']:
        raise ValueError(f'{gene} has no gene_id')

    # Get homology arms ================================================================================

    locus = await get_genome_region_from_annotation(annotation, 1000, 1000)
    feature = next(
        f
        for f in locus.features
        if (f.type == 'CDS') and (f"GeneID:{annotation['gene_id']}" in f.qualifiers['db_xref'])
    )

    left_homology_arm, right_homology_arm = get_homology_arms(locus, feature, cloning_type)

    left_primer = Primer(
        left_homology_arm + integration_binding_forward.upper(),
        name=integration_primer_name(gene, 'fwd', cloning_type),
    )
    right_primer = Primer(
        right_homology_arm + integration_binding_reverse.upper(),
        name=integration_primer_name(gene, 'rvs', cloning_type),
    )
    left_check_primer, right_check_primer = get_checking_primers(locus, feature, gene, cloning_type)
    # PCR ================================================================================================
    pcr_products = pcr_assembly(plasmid, left_primer, right_primer, limit=14, mismatches=0)
    pcr_products[0].name = 'amplified_marker'
    alleles = homologous_recombination_integration(locus, [pcr_products[0]], 80)
    modified_allele_name = allele_name(gene, cloning_type)
    alleles[0].name = modified_allele_name
    if len(alleles) > 1:
        raise ValueError(f'Multiple insertions possible for {gene}')
    # Check PCR ======================================================================================
    pcr_check1 = pcr_assembly(alleles[0], left_check_primer, common_primers[1], limit=14, mismatches=0)[0]
    pcr_check1.name = 'check_pcr_left'
    pcr_check2 = pcr_assembly(alleles[0], common_primers[0], right_check_primer, limit=14, mismatches=0)[0]
    pcr_check2.name = 'check_pcr_right'

    cs = CloningStrategy.from_dseqrecords([pcr_check1, pcr_check2])

    if not os.path.exists(os.path.join(output_dir, gene)):
        os.makedirs(os.path.join(output_dir, gene))

    gene_dir = os.path.join(output_dir, gene)
    with open(os.path.join(gene_dir, 'cloning_strategy.json'), 'w') as f:
        f.write(cs.model_dump_json(indent=2))
    with open(os.path.join(gene_dir, 'metadata.json'), 'w') as f:
        json.dump({'cloning_type': cloning_type, 'allele_name': modified_allele_name}, f)
