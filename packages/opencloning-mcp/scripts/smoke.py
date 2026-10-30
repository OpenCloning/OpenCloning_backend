"""Walk through the tools against the running server, over real HTTP, and print what happens.

Start the server first (uv run opencloning-mcp), then: uv run python packages/opencloning-mcp/scripts/smoke.py
"""

import asyncio
import json
import sys
import urllib.request

from fastapi.testclient import TestClient
from mcp import Client
from opencloning.main import app as cloning_app

SERVER_URL = sys.argv[1] if len(sys.argv) > 1 else 'http://localhost:8002/mcp'


async def call(client: Client, tool: str, **arguments) -> dict:
    result = await client.call_tool(tool, arguments)
    text = result.content[0].text
    print(f'\n>>> {tool}({", ".join(f"{k}={v!r}" for k, v in arguments.items())})')
    print(('ERROR: ' if result.is_error else '') + text)
    if result.is_error:
        raise SystemExit(1)
    return json.loads(text)


async def main():
    async with Client(SERVER_URL) as client:
        tools = await client.list_tools()
        print('Tools exposed by the server:')
        for tool in tools.tools:
            print(f'  - {tool.name}{tuple(tool.input_schema["properties"])}')

        strategy_id = (await call(client, 'start_strategy', description='smoke test'))['strategy_id']
        await call(client, 'describe_strategy', strategy_id=strategy_id)
        export = await call(client, 'get_strategy_json', strategy_id=strategy_id)

    print('\n>>> Download', export['download_url'])
    with urllib.request.urlopen(export['download_url']) as response:
        strategy = json.load(response)
    print(json.dumps(strategy)[:300])

    print('\n>>> Validate the downloaded JSON with the backend /validate endpoint')
    response = TestClient(cloning_app).post('/validate', json=strategy)
    print('status:', response.status_code, '| warnings:', response.headers.get('x-warning'))
    assert response.status_code == 200


asyncio.run(main())
