"""Tools to add starting sequences and primers to a strategy."""

import re
from pathlib import Path

from mcp.server.mcpserver.exceptions import ToolError

from opencloning.app_settings import settings

from . import cloning_api, names, storage
from .app import MAX_ADDGENE_PER_STRATEGY, mcp
from .products import add_product_to_strategy


def clean_or_none(name: str | None) -> str | None:
    return names.clean(name) if name else None


@mcp.tool()
def add_sequence_from_file(
    strategy_id: str,
    file_name: str,
    file_content: str,
    name: str | None = None,
    circularize: bool = False,
    product_index: int | None = None,
) -> dict:
    """Add a sequence from the text of a sequence file (GenBank, FASTA or EMBL).

    The format is guessed from the extension of file_name: .gb, .gbk, .ape, .fasta, .fa or .embl.
    Pass the file text exactly as it is. This only suits short files you only have as text: if you know the
    path of the file, use add_sequence_from_path; for binary files, use get_upload_link. If you only have the
    DNA letters, use add_typed_sequence.
    Set circularize=True to make the sequence circular (e.g. a plasmid in a FASTA file).
    If the file contains several sequences, the result has status "choose_product": call again
    with product_index to add one of them.
    By default the sequence keeps the name it has in the file, pass `name` to rename it.
    """
    params = {'circularize': circularize}
    if name is not None:
        params['output_name'] = names.clean(name)
    result = cloning_api.post('/read_from_file', files={'file': (file_name, file_content)}, params=params)
    return add_product_to_strategy(strategy_id, result, product_index)


SEQUENCE_FILE_EXTENSIONS = {'.gb', '.gbk', '.ape', '.fasta', '.fa', '.embl', '.dna'}


@mcp.tool()
def add_sequence_from_path(
    strategy_id: str,
    path: str,
    name: str | None = None,
    circularize: bool = False,
    product_index: int | None = None,
) -> dict:
    """Add a sequence from a file on the computer where this server runs, given its path.

    Prefer this to add_sequence_from_file when you know the path of the file (e.g. the user dragged it
    into Claude Code): nothing has to be retyped, and it works for binary SnapGene .dna files too.
    Supported extensions: .gb, .gbk, .ape, .fasta, .fa, .embl, .dna. If the file contains several sequences,
    the result has status "choose_product": call again with product_index. The sequence is named after the
    file unless you pass `name`.
    """
    file = Path(path).expanduser()
    if file.suffix.lower() not in SEQUENCE_FILE_EXTENSIONS:
        raise ToolError(
            f'Only sequence files can be read, with one of these extensions: {sorted(SEQUENCE_FILE_EXTENSIONS)}'
        )
    if not file.is_file():
        raise ToolError(f'There is no file at {path} on the computer where the server runs. Try get_upload_link.')
    if file.stat().st_size > settings.MAX_SEQUENCE_FILE_SIZE_MB * 1024 * 1024:
        raise ToolError(f'The file is larger than {settings.MAX_SEQUENCE_FILE_SIZE_MB} MB')

    # Named after the file: SnapGene files often have no name inside
    params = {'circularize': circularize, 'output_name': names.clean(name or file.stem)}
    result = cloning_api.post('/read_from_file', files={'file': (file.name, file.read_bytes())}, params=params)
    return add_product_to_strategy(strategy_id, result, product_index)


@mcp.tool()
def add_typed_sequence(strategy_id: str, sequence: str, circular: bool = False, name: str | None = None) -> dict:
    """Add a sequence from its DNA letters (A, C, G, T), e.g. a sequence the user pasted.

    Whitespace and line breaks are ignored. The sequence is linear and blunt unless circular=True.
    """
    source = {'id': 0, 'type': 'ManuallyTypedSource', 'output_name': names.clean(name) if name else None}
    typed_sequence = {'id': 0, 'sequence': ''.join(sequence.split()), 'circular': circular}
    result = cloning_api.post('/manually_typed', json={'source': source, 'sequence': typed_sequence})
    return add_product_to_strategy(strategy_id, result)


@mcp.tool()
def add_sequence_from_genbank(strategy_id: str, accession: str, name: str | None = None) -> dict:
    """Add a sequence from NCBI GenBank by its accession, e.g. "NM_001018957.2" or "CU329670.1".

    The whole record is downloaded, so this is meant for plasmids, genes and other short records
    (up to 500 kb), not whole chromosomes. By default the sequence keeps the name GenBank gives it.
    """
    source = {'id': 0, 'type': 'NCBISequenceSource', 'repository_id': accession, 'output_name': clean_or_none(name)}
    result = cloning_api.post('/repository_id/genbank', json=source)
    return add_product_to_strategy(strategy_id, result)


@mcp.tool()
def add_sequence_from_addgene(strategy_id: str, addgene_id: str, name: str | None = None) -> dict:
    """Add a plasmid from Addgene by its catalog number, e.g. "39296" (the number in addgene.org/39296).

    Needs the server to be configured with an Addgene API token. By default the sequence keeps the
    name of the plasmid in Addgene. A strategy can import a limited number of plasmids from Addgene.
    """
    imported = sum(source['type'] == 'AddgeneIdSource' for source in storage.load_strategy(strategy_id)['sources'])
    if imported >= MAX_ADDGENE_PER_STRATEGY:
        raise ToolError('Too many AddGene requests')
    source = {'id': 0, 'type': 'AddgeneIdSource', 'repository_id': addgene_id, 'output_name': clean_or_none(name)}
    result = cloning_api.post('/repository_id/addgene', json=source)
    return add_product_to_strategy(strategy_id, result)


@mcp.tool()
def add_primer(strategy_id: str, name: str, sequence: str) -> dict:
    """Add a primer (5' to 3', A/C/G/T only) to the strategy and return its id.

    Use the primer id in the pcr tool. Primers are not sequences: they don't appear among the
    sequences of the strategy, only in its primers list.
    """
    sequence = ''.join(sequence.split())
    if not re.fullmatch('[ACGTacgt]+', sequence):
        raise ToolError('The primer sequence can only contain the letters A, C, G and T.')
    primer_id = storage.add_primer(strategy_id, name, sequence)
    return {'id': primer_id, 'name': name, 'length': len(sequence)}
