from fastapi import HTTPException
from urllib.parse import quote, urljoin
import math
import asyncio
from Bio.Restriction.Restriction import RestrictionBatch
from Bio.Seq import reverse_complement
from pydna.dseqrecord import Dseqrecord
from pydna.dseq import Dseq
from opencloning_linkml.datamodel import (
    PlannotateAnnotationReport,
    TextFileSequence,
    SequenceFileFormat,
)
from pydna.opencloning_models import (
    AddgeneIdSource,
    OpenDNACollectionsSource,
    SEVASource,
    SnapGenePlasmidSource,
    WekWikGeneIdSource,
    BenchlingUrlSource,
    IGEMSource,
    EuroscarfSource,
)

from bs4 import BeautifulSoup
from pydna.common_sub_strings import common_sub_strings
from Bio.SeqIO import parse as seqio_parse
from pydna.parsers import parse as pydna_parse
import io

from opencloning.catalogs import iGEM2024_catalog, openDNA_collections_catalog, seva_catalog, snapgene_catalog
from . import app_settings
from .http_client import get_http_client, ConnectError, TimeoutException
from .ncbi_requests import get_genbank_sequence
from typing import Callable


class AddgeneClientManager:
    def __init__(self):
        self._client = None
        self._client_loop = None
        self._login_lock = asyncio.Lock()
        self._base_url = 'https://www.addgene.org'
        self._login_url = 'https://www.addgene.org/users/login/'

    async def get_client(self):
        running_loop = asyncio.get_running_loop()
        if self._client is None or self._client_loop is not running_loop:
            self._client = get_http_client()
            self._client_loop = running_loop
        return self._client

    async def get_page(self, addgene_id: str) -> BeautifulSoup:
        url = f'{self._base_url}/{addgene_id}/sequences/'
        resp = await (await self.get_client()).get(url)
        if resp.status_code == 404:
            raise HTTPException(404, 'wrong addgene id')
        bs = BeautifulSoup(resp.content, 'html.parser')
        if _has_addgene_anonymous_sequence_alert(bs):
            resp = await self.login_and_get(f'/{addgene_id}/sequences/')
            bs = BeautifulSoup(resp.content, 'html.parser')
            if not _has_addgene_anonymous_sequence_alert(bs):
                return bs
            raise HTTPException(  # pragma: no cover
                503,
                'could not access Addgene sequences with the current session. Check ADDGENE_USERNAME/ADDGENE_PASSWORD and ensure your access complies with Addgene Terms of Use. For more information, see README.md.',
            )
        else:  # pragma: no cover
            # This cannot be reached in the tests because it re-logs every time
            return bs

    async def login_and_get(self, redirect_url: str):
        addgene_username = app_settings.settings.ADDGENE_USERNAME
        addgene_password = app_settings.settings.ADDGENE_PASSWORD
        if addgene_username is None or addgene_password is None:
            raise HTTPException(
                503,
                'Addgene access requires credentials. Please set ADDGENE_USERNAME and ADDGENE_PASSWORD environment '
                'variables and ensure your use complies with Addgene Terms of Use. For more information, see README.md.',
            )

        async with self._login_lock:
            addgene_client = await self.get_client()
            login_page_response = await addgene_client.get(self._login_url)
            login_page_soup = BeautifulSoup(login_page_response.content, 'html.parser')
            csrf_input = login_page_soup.find('input', attrs={'name': 'csrfmiddlewaretoken'})
            if csrf_input is None or csrf_input.get('value') is None:  # pragma: no cover
                raise HTTPException(503, 'could not retrieve Addgene login token')

            login_payload = {
                'username': addgene_username,
                'password': addgene_password,
                'csrfmiddlewaretoken': csrf_input['value'],
                'next': redirect_url,
            }
            login_response = await addgene_client.post(
                self._login_url, data=login_payload, headers={'Referer': self._login_url}, follow_redirects=True
            )
            if login_response.status_code >= 400:  # pragma: no cover
                raise HTTPException(503, 'could not log in to Addgene')
            return login_response


_addgene_manager = AddgeneClientManager()


def _has_addgene_anonymous_sequence_alert(soup: BeautifulSoup) -> bool:
    return soup.find(class_='anonymous-user-sequence-alert') is not None


def format_sequence_genbank(seq: Dseqrecord, seq_name: str = None) -> TextFileSequence:

    if seq_name is not None:
        seq.name = seq_name
    elif seq.name.lower() == 'exported':
        correct_name(seq)

    return TextFileSequence(
        id=int(seq.id) if seq.id is not None and str(seq.id).isdigit() else 0,
        file_content=seq.format('genbank'),
        sequence_file_format=SequenceFileFormat('genbank'),
        overhang_crick_3prime=seq.seq.ovhg,
        overhang_watson_3prime=seq.seq.watson_ovhg,
    )


def read_dsrecord_from_json(seq: TextFileSequence) -> Dseqrecord:
    with io.StringIO(seq.file_content) as handle:
        try:
            out_dseq_record: Dseqrecord = custom_file_parser(handle, 'genbank')[0]
        except ValueError as e:
            raise HTTPException(
                422, f'The file for sequence with id {seq.id} is not in a valid genbank format: {e}'
            ) from e
    if seq.overhang_watson_3prime != 0 or seq.overhang_crick_3prime != 0:
        out_dseq_record.seq = Dseq.from_full_sequence_and_overhangs(
            str(out_dseq_record.seq), seq.overhang_crick_3prime, seq.overhang_watson_3prime
        )
    # We set the id to the integer converted to integer (this is only
    # useful for assemblies)
    out_dseq_record.id = str(seq.id)
    return out_dseq_record


def get_invalid_enzyme_names(enzyme_names_list: list[str | None]) -> list[str]:
    rest_batch = RestrictionBatch()
    invalid_names = list()
    for name in enzyme_names_list:
        # Empty enzyme names are the natural edges of the molecule
        if name is not None:
            try:
                rest_batch.format(name)
            except ValueError:
                invalid_names.append(name)
    return invalid_names


async def get_sequences_from_file_url(
    url: str,
    format: SequenceFileFormat = SequenceFileFormat('genbank'),
    params: dict | None = None,
    headers: dict | None = None,
    get_function: None | Callable = None,
) -> list[Dseqrecord]:

    if get_function is None:
        async with get_http_client() as client:
            resp = await client.get(url, params=params, headers=headers)
    else:
        resp = await get_function(url, params=params, headers=headers)

    if math.floor(resp.status_code / 100) == 5:
        raise HTTPException(503, 'the external server (not OpenCloning) returned an error')
    elif math.floor(resp.status_code / 100) != 2:
        raise HTTPException(404, 'file requested from url not found')
    try:
        if format == SequenceFileFormat('snapgene'):
            return custom_file_parser(io.BytesIO(resp.content), format)
        else:
            return custom_file_parser(io.StringIO(resp.text), format)
    except ValueError as e:
        raise HTTPException(400, f'{e}') from e


async def request_from_snapgene(plasmid_set: dict, plasmid_name: str) -> Dseqrecord:
    if plasmid_set not in snapgene_catalog:
        raise HTTPException(404, 'invalid plasmid set')
    if plasmid_name not in snapgene_catalog[plasmid_set]:
        raise HTTPException(404, f'{plasmid_name} is not part of {plasmid_set}')
    url = f'https://www.snapgene.com/local/fetch.php?set={plasmid_set}&plasmid={plasmid_name}'
    seqs = await get_sequences_from_file_url(url, SequenceFileFormat('snapgene'))
    seq = seqs[0]
    seq.name = plasmid_name
    seq.source = SnapGenePlasmidSource(repository_id=f'{plasmid_set}/{plasmid_name}')
    return seq


async def request_from_addgene(repository_id: str) -> Dseqrecord:
    bs = await _addgene_manager.get_page(repository_id)
    addgene_client = await _addgene_manager.get_client()
    # Get a span.material-name from the soup, see https://github.com/OpenCloning/OpenCloning_backend/issues/182
    plasmid_name = bs.find('span', class_='material-name').text.replace(' ', '_')

    # Find the link to either the addgene-full (preferred) or depositor-full (secondary)
    for addgene_sequence_type in ['depositor-full', 'addgene-full']:
        if bs.find(id=addgene_sequence_type) is not None:
            sequence_links = bs.find(id=addgene_sequence_type).find_all(class_='genbank-file-download')
            sequence_file_url = sequence_links[0].get('href')
            sequence_file_url = urljoin('https://www.addgene.org', sequence_file_url)
            break
    else:
        raise HTTPException(
            404,
            f'The requested plasmid does not have full sequences, see https://www.addgene.org/{repository_id}/sequences/',
        )

    try:
        file_response = await addgene_client.get(sequence_file_url, follow_redirects=True)
    except HTTPException:  # pragma: no cover
        await _addgene_manager.login_and_get('')
        file_response = await addgene_client.get(sequence_file_url, follow_redirects=True)
        if file_response.status_code != 200:
            raise HTTPException(503, 'Failed to download sequence file from Addgene')

    dseqr = custom_file_parser(io.StringIO(file_response.text), SequenceFileFormat('genbank'))[0]

    dseqr.name = plasmid_name
    dseqr.source = AddgeneIdSource(
        repository_id=repository_id,
        sequence_file_url=sequence_file_url,
        addgene_sequence_type=addgene_sequence_type,
    )
    return dseqr


async def request_from_wekwikgene(repository_id: str) -> Dseqrecord:
    url = f'https://wekwikgene.wllsb.edu.cn/plasmids/{repository_id}'
    async with get_http_client() as client:
        resp = await client.get(url)
    if resp.status_code == 404:
        raise HTTPException(404, 'invalid wekwikgene id')
    soup = BeautifulSoup(resp.content, 'html.parser')
    # Get the sequence file URL from the page
    sequence_file_url = soup.find('a', text=lambda x: x and 'Download Sequence' in x).get('href')
    sequence_name = soup.find('h1', class_='plasmid__info__name').text.replace(' ', '_')
    seq = (await get_sequences_from_file_url(sequence_file_url, 'snapgene'))[0]
    seq.name = sequence_name
    seq.source = WekWikGeneIdSource(repository_id=repository_id, sequence_file_url=sequence_file_url)
    return seq


async def get_seva_plasmid(repository_id: str) -> Dseqrecord:
    if repository_id not in seva_catalog:
        raise HTTPException(404, 'invalid SEVA id')
    link = seva_catalog[repository_id]
    if 'http' not in link:
        seq = await get_genbank_sequence(link)
    else:
        seqs = await get_sequences_from_file_url(link)
        seq = seqs[0]

    if not seq.circular:
        seq = seq.looped()
    seq.name = repository_id
    sequence_file_url = link if 'http' in link else f'https://www.ncbi.nlm.nih.gov/nuccore/{link}'
    seq.source = SEVASource(repository_id=repository_id, sequence_file_url=sequence_file_url)
    return seq


async def get_sequence_from_benchling_url(url: str) -> Dseqrecord:
    dseqs = await get_sequences_from_file_url(url)
    dseq = dseqs[0]
    dseq.source = BenchlingUrlSource(repository_id=url)
    return dseq


def correct_name(dseq: Dseqrecord):
    # Can set the name from keyword if locus is set to Exported
    if dseq.name.lower() == 'exported' and dseq.locus.lower() == 'exported' and 'keywords' in dseq.annotations:
        dseq.name = dseq.annotations['keywords'][0].replace(' ', '_')


def oligonucleotide_hybridization_overhangs(
    fwd_oligo_seq: str, rvs_oligo_seq: str, minimal_annealing: int
) -> list[int]:
    """
    Returns possible overhangs between two oligos, and returns an error if mismatches are found.

    see https://github.com/OpenCloning/OpenCloning_backend/issues/302 for notation

    """
    matches = common_sub_strings(fwd_oligo_seq.lower(), reverse_complement(rvs_oligo_seq.lower()), minimal_annealing)

    for pos_fwd, pos_rvs, length in matches:

        if (pos_fwd != 0 and pos_rvs != 0) or (
            pos_fwd + length < len(fwd_oligo_seq) and pos_rvs + length < len(rvs_oligo_seq)
        ):
            raise ValueError('The oligonucleotides can anneal with mismatches')

    # Return possible overhangs
    return [pos_rvs - pos_fwd for pos_fwd, pos_rvs, length in matches]


def parse(file_streamer: io.BytesIO | io.StringIO, sequence_file_format: SequenceFileFormat) -> list[Dseqrecord]:
    if sequence_file_format == SequenceFileFormat('genbank'):
        return pydna_parse(file_streamer.read(), is_path=False)
    else:
        return seqio_parse(file_streamer, sequence_file_format)


def custom_file_parser(
    file_streamer: io.BytesIO | io.StringIO, sequence_file_format: SequenceFileFormat, circularize: bool = False
) -> list[Dseqrecord]:
    """
    Parse a file with SeqIO.parse (specifying the format and using the topology annotation to determine circularity).

    If the format is genbank and the parsing of the LOCUS line fails, fallback to custom regex-based parsing.
    """

    out = list()

    with file_streamer as handle:

        for parsed_seq in parse(handle, sequence_file_format):
            circularize = circularize or (
                'topology' in parsed_seq.annotations.keys() and parsed_seq.annotations['topology'] == 'circular'
            )
            out.append(Dseqrecord(parsed_seq, circular=circularize))

    if len(out) == 0:
        raise ValueError('No sequences found in file')
    return out


async def get_sequence_from_euroscarf_url(plasmid_id: str) -> Dseqrecord:
    url = f'http://www.euroscarf.de/plasmid_details.php?accno={plasmid_id}'
    async with get_http_client() as client:
        resp = await client.get(url)

    # Use beautifulsoup to parse the html
    soup = BeautifulSoup(resp.text, 'html.parser')
    # Identify if it's an error (seems to be a php error log without a body tag)
    body_tag = soup.find('body')
    if body_tag is None:
        if 'Call to a member function getName()' in resp.text:
            raise HTTPException(404, 'invalid euroscarf id')
        else:
            msg = f'Could not retrieve plasmid details, double-check the euroscarf site: {url}'
            raise HTTPException(503, msg)
    # Get the download link
    subpath = soup.find('a', href=lambda x: x and x.startswith('files/dna'))
    if subpath is None:
        msg = f'Could not retrieve plasmid details, double-check the euroscarf site: {url}'
        raise HTTPException(503, msg)
    genbank_url = f'http://www.euroscarf.de/{subpath.get("href")}'
    seq = (await get_sequences_from_file_url(genbank_url))[0]
    # Sometimes the files do not contain correct topology information, so we loop them
    if not seq.circular:
        seq = seq.looped()
    seq.source = EuroscarfSource(repository_id=plasmid_id)
    return seq


async def annotate_with_plannotate(
    file_content: str, file_name: str, url: str, timeout: int = 20
) -> tuple[Dseqrecord, PlannotateAnnotationReport, str]:
    async with get_http_client() as client:
        try:
            response = await client.post(
                url,
                files={'file': (file_name, file_content, 'text/plain')},
                timeout=timeout,
            )
            if response.status_code != 200:
                detail = response.json().get('detail', 'plannotate server error')
                raise HTTPException(response.status_code, detail)
            data = response.json()
            dseqr = custom_file_parser(io.StringIO(data['gb_file']), 'genbank')[0]
            report = [PlannotateAnnotationReport.model_validate(r) for r in data['report']]
            return dseqr, report, data['version']
        except TimeoutException as e:
            raise HTTPException(504, 'plannotate server timeout') from e
        except ConnectError as e:
            raise HTTPException(500, 'cannot connect to plannotate server') from e


async def get_sequence_from_openDNA_collections(collection_name: str, plasmid_id: str) -> Dseqrecord:
    if collection_name not in openDNA_collections_catalog:
        raise HTTPException(404, 'invalid openDNA collections collection')
    plasmid = next((item for item in openDNA_collections_catalog[collection_name] if item['id'] == plasmid_id), None)
    if plasmid is None:
        raise HTTPException(404, f'plasmid {plasmid_id} not found in {collection_name}')

    path = quote(plasmid['path'])
    url = f'https://assets.opencloning.org/open-dna-collections/{path}'
    seqs = await get_sequences_from_file_url(url)
    seq = seqs[0]
    seq.name = plasmid['name'] if plasmid['name'] is not None else plasmid_id
    seq.source = OpenDNACollectionsSource(repository_id=f'{collection_name}/{plasmid_id}', sequence_file_url=url)
    return seq


async def get_sequence_from_iGEM2024(part: str, backbone: str) -> Dseqrecord:
    all_plasmids = [item for collection in iGEM2024_catalog.values() for item in collection]
    plasmid = next((item for item in all_plasmids if item['part'] == part and item['backbone'] == backbone), None)
    if plasmid is None:
        raise HTTPException(404, f'plasmid {part}-{backbone} not found in iGEM 2024')
    url = f'https://assets.opencloning.org/annotated-igem-distribution/results/plasmids/{plasmid["id"]}.gb'
    seqs = await get_sequences_from_file_url(url)
    seq = seqs[0]
    seq.name = f'{part}-{backbone}'
    seq.source = IGEMSource(repository_id=f'{part}-{backbone}', sequence_file_url=url)
    return seq
