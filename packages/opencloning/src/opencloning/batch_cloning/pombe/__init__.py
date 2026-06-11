from fastapi import Form, File, UploadFile, HTTPException
from typing import Annotated, Literal
import os
import tempfile
import pandas as pd
from fastapi.responses import FileResponse, HTMLResponse
from .pombe_clone import main as pombe_clone
from .pombe_summary import main as pombe_summary
from .pombe_gather import main as pombe_gather
import shutil
from ...get_router import get_router
from fastapi import Request
from opencloning.dna_functions import get_sequence_from_euroscarf_url, request_from_addgene, request_from_snapgene
from pydna.primer import Primer
from pydna.opencloning_models import UploadedFileSource
from pydna.parsers import parse as pydna_parse
from pydna.parsers import parse_snapgene

router = get_router()


@router.get('/batch_cloning/pombe')
async def get_batch_cloning_page(request: Request):
    return FileResponse(os.path.join(os.path.dirname(__file__), 'index.html'))


ASSEMBLY_ACCESSION = 'GCF_000002945.2'

DEFAULT_PLASMID_OPTIONS = {
    'gene_deletion': {
        'kanmx6': ('addgene', '39296', None),
        'natmx6': ('snapgene', 'yeast_plasmids', 'pFA6a-natMX6'),
        'hphmx6': ('snapgene', 'yeast_plasmids', 'pFA6a-hphMX6'),
    },
    'gene_cterm_tagging': {
        'kanmx6': ('addgene', '87023', None),
        'natmx6': ('addgene', '52693', None),
        'hphmx6': ('addgene', '105156', None),
    },
    'promoter_not_tag': {
        'kanmx6': ('addgene', '39280', None),  # pFA6a-kanMX6-P3nmt1
        'natmx6': ('euroscarf', 'P30425', None),  # pFA6a-natMX6-P3nmt1
        'hphmx6': ('addgene', '105162', None),  # pFA6a-hphMX6-3nmt1
    },
    'promoter_with_tag': {
        'kanmx6': ('addgene', '39289', None),  # pFA6a-kanMX6-P3nmt1-GFP
        'natmx6': ('addgene', '19345', None),  # pFA6a-natMX6-P3nmt1-3FLAG
        'hphmx6': ('addgene', '19348', None),  # pFA6a-hphMX6-P3nmt1-3FLAG
    },
}


@router.post('/batch_cloning/pombe')
async def post_batch_cloning(
    cloning_type: Annotated[
        Literal['gene_deletion', 'gene_cterm_tagging', 'promoter_not_tag', 'promoter_with_tag'], Form(...)
    ],
    desired_output: Annotated[Literal['simulate_cloning', 'primers_only'], Form(...)],
    gene_list: str = Form(...),
    integration_binding_forward: str = Form(..., pattern=r'^[ACGTacgt]+$', min_length=1),
    integration_binding_reverse: str = Form(..., pattern=r'^[ACGTacgt]+$', min_length=1),
    plasmid_file: UploadFile | None = File(None),
    addgene_id: str | None = Form(None),
    plasmid_option: Annotated[Literal['addgene', 'file', 'default'], Form(...)] = None,
    checking_primer_forward: str = Form(..., pattern=r'^[ACGTacgt]+$', min_length=1),
    checking_primer_reverse: str = Form(..., pattern=r'^[ACGTacgt]+$', min_length=1),
    resistance_marker: Annotated[Literal['kanmx6', 'natmx6', 'hphmx6', 'other'], Form(...)] = None,
):
    genes = [gene.strip() for gene in gene_list.split() if gene.strip()]

    if not genes:
        raise HTTPException(status_code=400, detail='No valid genes provided')

    common_primers = [
        Primer(checking_primer_forward, name='common_insert_fwd'),
        Primer(checking_primer_reverse, name='common_insert_rvs'),
    ]

    if plasmid_option == 'default':
        try:
            mode, first, second = DEFAULT_PLASMID_OPTIONS[cloning_type][resistance_marker]
            if mode == 'addgene':
                plasmid = await request_from_addgene(first)
            elif mode == 'euroscarf':
                plasmid = await get_sequence_from_euroscarf_url(first)
            else:
                plasmid = await request_from_snapgene(second, first)
        except KeyError:
            raise HTTPException(
                status_code=400, detail=f'Resistance marker {resistance_marker} is not supported for default plasmid'
            )

    elif plasmid_option == 'file':
        assert plasmid_file is not None
        assert plasmid_file.filename is not None
        file_content = await plasmid_file.read()
        if plasmid_file.filename.endswith('.dna'):
            plasmid = parse_snapgene(file_content)[0]
        else:
            plasmid = pydna_parse(file_content)[0]
            plasmid.source = UploadedFileSource(
                file_name=plasmid_file.filename,
                sequence_file_format=plasmid.annotations['pydna_parse_sequence_file_format'],
                index_in_file=0,
            )
    if plasmid_option == 'addgene':
        assert addgene_id is not None
        plasmid = await request_from_addgene(addgene_id)

    with tempfile.TemporaryDirectory() as temp_dir:
        for gene in genes:
            await pombe_clone(
                gene,
                ASSEMBLY_ACCESSION,
                temp_dir,
                plasmid,
                common_primers,
                integration_binding_forward,
                integration_binding_reverse,
                cloning_type,
            )

        try:
            pombe_summary(temp_dir)
            pombe_gather(temp_dir)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f'Summary failed: {e}')

        if desired_output == 'primers_only':
            primer_summary_path = os.path.join(temp_dir, 'primer_summary.tsv')
            primer_df = pd.read_csv(primer_summary_path, sep='\t')
            return HTMLResponse(
                content=primer_df.to_html(
                    index=False,
                    border=0,
                    classes='primer-summary-table',
                    float_format='%.1f',
                )
            )

        zip_filename = f'{temp_dir}_archive'
        shutil.make_archive(zip_filename, 'zip', temp_dir)
        zip_file = f'{zip_filename}.zip'
        return FileResponse(zip_file, filename='batch_cloning_output.zip')
