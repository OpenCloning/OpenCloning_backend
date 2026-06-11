import os
from pydna.dseqrecord import Dseqrecord
from pydna.assembly2 import homologous_recombination_integration, pcr_assembly
from opencloning.ncbi_requests import get_annotations_from_query, get_genome_region_from_annotation
from pydna.primer import Primer
from pydna.opencloning_models import CloningStrategy
from pydna.utils import location_boundaries

from opencloning.primer_design import primer_to_amplify_fragment_of_given_size_knowing_other_primer


async def main(
    gene: str,
    assembly_accession: str,
    output_dir: str,
    plasmid: Dseqrecord,
    common_primers: list[Primer],
    integration_binding_forward: str = 'CGGATCCCCGGGTTAATTAA',
    integration_binding_reverse: str = 'GAATTCGAGCTCGTTTAAAC',
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
    start, end = (int(i) for i in location_boundaries(feature.location))
    left_homology_arm = str(locus.seq[start - 80 : start]).lower()
    right_homology_arm = str(locus.seq[end : end + 80].reverse_complement()).lower()
    left_primer = Primer(
        left_homology_arm + integration_binding_forward.upper(),
        name=f'{gene}_deletion_fwd',
    )
    right_primer = Primer(
        right_homology_arm + integration_binding_reverse.upper(),
        name=f'{gene}_deletion_rvs',
    )
    # PCR ================================================================================================
    pcr_products = pcr_assembly(plasmid, left_primer, right_primer, limit=14, mismatches=0)
    pcr_products[0].name = 'amplified_marker'
    alleles = homologous_recombination_integration(locus, [pcr_products[0]], 40)
    alleles[0].name = f'{gene}Δ'
    # Check PCR ======================================================================================
    right_check_primer = primer_to_amplify_fragment_of_given_size_knowing_other_primer(
        alleles[0], common_primers[0], True, [1100, 1200]
    )
    right_check_primer.name = f'{gene}_check_pcr_right'
    left_check_primer = primer_to_amplify_fragment_of_given_size_knowing_other_primer(
        alleles[0], common_primers[1], False, [1100, 1200]
    )
    left_check_primer.name = f'{gene}_check_pcr_left'
    pcr_check1 = pcr_assembly(alleles[0], left_check_primer, common_primers[1], limit=14, mismatches=0)[0]
    pcr_check1.name = 'check_pcr_left'
    pcr_check2 = pcr_assembly(alleles[0], common_primers[0], right_check_primer, limit=14, mismatches=0)[0]
    pcr_check2.name = 'check_pcr_right'

    cs = CloningStrategy.from_dseqrecords([pcr_check1, pcr_check2])

    if not os.path.exists(os.path.join(output_dir, gene)):
        os.makedirs(os.path.join(output_dir, gene))

    with open(os.path.join(output_dir, gene, 'cloning_strategy.json'), 'w') as f:
        f.write(cs.model_dump_json(indent=2))
