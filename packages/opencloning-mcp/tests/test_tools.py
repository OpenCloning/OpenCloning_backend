"""Call the tools through an in-memory MCP client, the same way a host like Claude Code does."""

import json

import pytest
from fastapi.testclient import TestClient
from mcp import Client

from opencloning_mcp.server import mcp


async def call(client: Client, tool: str, **arguments) -> dict:
    """Call a tool and return its result as a dict. Fails if the tool raised an error."""
    result = await client.call_tool(tool, arguments)
    assert not result.is_error, result.content[0].text
    return json.loads(result.content[0].text)


@pytest.mark.anyio
async def test_start_describe_and_export(client: Client):
    strategy_id = (await call(client, 'start_strategy', description='test'))['strategy_id']

    description = await call(client, 'describe_strategy', strategy_id=strategy_id)
    assert description == {'description': 'test', 'sequences': [], 'primers': []}

    export = await call(client, 'get_strategy_json', strategy_id=strategy_id)
    assert export['download_url'].endswith(f'/strategies/{strategy_id}.json')
    assert export['number_of_sequences'] == 0


@pytest.mark.anyio
async def test_unknown_strategy_id_is_reported_to_the_model(client: Client):
    result = await client.call_tool('describe_strategy', {'strategy_id': 'wrong'})
    assert result.is_error
    assert 'Unknown or expired strategy_id' in result.content[0].text


@pytest.mark.anyio
async def test_download_route(client: Client):
    strategy_id = (await call(client, 'start_strategy'))['strategy_id']
    http = TestClient(mcp.streamable_http_app())

    response = http.get(f'/strategies/{strategy_id}.json')
    assert response.status_code == 200
    assert response.json()['sequences'] == []

    assert http.get('/strategies/wrong.json').status_code == 404
