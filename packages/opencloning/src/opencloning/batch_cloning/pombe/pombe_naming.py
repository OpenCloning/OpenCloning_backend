from typing import Literal

CloningType = Literal['gene_deletion', 'gene_cterm_tagging']


def integration_primer_label(cloning_type: CloningType) -> str:
    return 'deletion' if cloning_type == 'gene_deletion' else 'tag'


def allele_name(gene: str, cloning_type: CloningType) -> str:
    return f'{gene}Δ' if cloning_type == 'gene_deletion' else f'{gene}-tagged'


def integration_primer_name(gene: str, direction: Literal['fwd', 'rvs'], cloning_type: CloningType) -> str:
    return f'{gene}_{integration_primer_label(cloning_type)}_{direction}'


def primer_summary_name(gene: str, primer_key: str, cloning_type: CloningType) -> str:
    if primer_key == 'primer_fwd':
        return integration_primer_name(gene, 'fwd', cloning_type)
    if primer_key == 'primer_rvs':
        return integration_primer_name(gene, 'rvs', cloning_type)
    if primer_key == 'primer_fwd_check':
        return f'{gene}_fwd_check'
    if primer_key == 'primer_rvs_check':
        return f'{gene}_rvs_check'
    raise ValueError(f'Unknown primer key: {primer_key}')
