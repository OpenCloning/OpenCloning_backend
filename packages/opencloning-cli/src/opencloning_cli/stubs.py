from pydantic import BaseModel, Field
from typing import Generator


class StubRequest(BaseModel):
    endpoint: str
    method: str = Field(..., pattern=r'^(GET|POST|PUT|DELETE|PATCH)$')
    name: str
    params: dict | None = None
    body: dict | list | None = None
    headers: dict | None = None
    body_from_stub: str | None = None
    body_from_example: str | None = None
    multipart_files: list[dict[str, str]] | None = None
    binary_response: bool = False
    reset_db: bool = False
    expected_status_code: int = 200


class StubResponse(BaseModel):
    body: dict | list
    status_code: int
    headers: dict


class RecordedStub(BaseModel):
    name: str
    endpoint: str
    method: str = Field(..., pattern=r'^(GET|POST|PUT|DELETE|PATCH)$')
    name: str
    params: dict | None = None
    body: dict | list | None = None
    headers: dict | None = None
    response: StubResponse


def get_stub(dirname: str, stub_name: str) -> RecordedStub:
    with open(f'{dirname}/{stub_name}.json', 'r') as f:
        return RecordedStub.model_validate_json(f.read())


def get_selected_primer_id(dirname: str, stub_name: str) -> int:
    stub = get_stub(dirname, stub_name)
    return next(item for item in stub.response.body['items'] if item['name'] == 'lacZ_attB1_fwd')['id']


def get_selected_sequence_id(dirname: str, stub_name: str) -> int:
    stub = get_stub(dirname, stub_name)
    return next(item for item in stub.response.body['items'] if item['name'] == 'ase1_CDS_PCR')['id']


def stubs(dirname: str) -> Generator[StubRequest, None, None]:
    yield StubRequest(
        name='get_primers',
        endpoint='/primers',
        method='GET',
    )
    yield StubRequest(
        name='get_primers_search_by_name',
        endpoint='/primers',
        method='GET',
        params={'name': 'lacZ_attB1_fwd'},
    )
    yield StubRequest(
        name='get_primer',
        endpoint=f'/primers/{get_selected_primer_id(dirname, "get_primers")}',
        method='GET',
    )
    yield StubRequest(
        name='post_primer',
        endpoint='/primers',
        method='POST',
        body={'name': 'new', 'sequence': 'GGCC'},
        reset_db=True,
    )
    yield StubRequest(
        name='patch_primer',
        endpoint=f'/primers/{get_selected_primer_id(dirname, "get_primers")}',
        method='PATCH',
        body={'name': 'lacZ_renamed'},
        reset_db=True,
    )
    yield StubRequest(
        name='get_sequences',
        endpoint='/sequences',
        method='GET',
    )
    yield StubRequest(
        name='get_sequences_search_by_name',
        endpoint='/sequences',
        method='GET',
        params={'name': 'ase1_CDS_PCR'},
    )
    yield StubRequest(
        name='get_sequence',
        endpoint=f'/sequences/{get_selected_sequence_id(dirname, "get_sequences")}',
        method='GET',
    )
    yield StubRequest(
        name='patch_sequence',
        endpoint=f'/sequences/{get_selected_sequence_id(dirname, "get_sequences")}',
        method='PATCH',
        body={'name': 'ase1_renamed'},
        reset_db=True,
    )
    yield StubRequest(
        name='get_sequence_by_uid',
        endpoint='/sequences/by-uid/example_sequencing-sample',
        method='GET',
    )
    yield StubRequest(
        name='get_sequences_by_seguid',
        endpoint='/sequences/by-seguid/ldseguid=oMGruVpBiElY0ffP28XC_BlHXv8',
        method='GET',
    )
    yield StubRequest(
        name='get_text_file_sequence',
        endpoint=f'/sequences/{get_selected_sequence_id(dirname, "get_sequences")}/text_file_sequence',
        method='GET',
    )
    yield StubRequest(
        name='get_cloning_strategy',
        endpoint=f'/sequences/{get_selected_sequence_id(dirname, "get_sequences")}/cloning_strategy',
        method='GET',
    )
    yield StubRequest(
        name='get_sequence_primers',
        endpoint=f'/sequences/{get_selected_sequence_id(dirname, "get_sequences")}/primers',
        method='GET',
    )
    yield StubRequest(
        name='post_sequence',
        endpoint='/sequences',
        method='POST',
        body_from_example='cs_pcr',
        reset_db=True,
    )
    # StubRequest(
    #     name='post_sequence_search',
    #     endpoint='/sequences/search',
    #     method='POST',
    #     body_from_stub='get_text_file_sequence',
    # )
    # StubRequest(
    #     name='post_sequence_sequencing_files',
    #     endpoint='/sequences/10/sequencing_files',
    #     method='POST',
    #     multipart_files=[
    #         {
    #             'filename': 'run.ab1',
    #             'content': 'SEQUENCING-RUN-1',
    #             'content_type': 'application/octet-stream',
    #         }
    #     ],
    # )
    # StubRequest(
    #     name='get_sequence_sequencing_files',
    #     endpoint='/sequences/10/sequencing_files',
    #     method='GET',
    # )
    # StubRequest(
    #     name='download_sequencing_file',
    #     endpoint='/sequencing_files/{last_file_id}/download',
    #     method='GET',
    #     binary_response=True,
    #     reset_db=True,
    # )
