"""The MCP server object and its settings.

Tools are registered on `mcp` in the tools_*.py modules, and server.py puts everything together.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from mcp.server import MCPServer

from . import db, storage

PORT = int(os.environ.get('OPENCLONING_MCP_PORT', '8002'))
# Used to build the download links given to the user
BASE_URL = os.environ.get('OPENCLONING_MCP_BASE_URL', f'http://localhost:{PORT}').rstrip('/')

logger = logging.getLogger(__name__)

# Sent to the model when it connects: how to use the tools together
INSTRUCTIONS = f"""
This server builds OpenCloning cloning strategies step by step. The strategy is stored on the server:
you never pass sequences around, you refer to sequences and primers by the integer ids the tools return.

Workflow:
1. Call start_strategy once and keep the returned strategy_id. Pass it to every other tool.
2. Add the starting sequences with the add_sequence_* tools, and primers with add_primer.
   Each returns the id of the new sequence or primer.
3. Run cloning operations (restriction digest, PCR, ligation, assemblies...) on those ids.
   Each operation adds exactly one new sequence to the strategy and returns its id.
4. If a tool returns status "choose_product", nothing was added yet: pick the candidate that matches what
   the user wants (ask the user if it is not clear) and call the same tool again with product_index.
5. Call describe_strategy to see every sequence in the strategy and how it was made.
6. When the user is done, call get_strategy_json and give them the download link. The file opens in
   the OpenCloning web app.

Only use ids returned by these tools. Strategies are deleted after {storage.INACTIVITY_MINUTES} minutes without
use, so offer the download link at the end of each task.
"""


async def delete_inactive_strategies_every_minute():
    while True:
        deleted = storage.delete_inactive_strategies()
        if deleted:
            logger.info('Deleted %d inactive strategies', deleted)
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(server: MCPServer):
    """Runs once: the code before `yield` at startup, the code after it at shutdown."""
    db.init_db()
    cleanup_task = asyncio.create_task(delete_inactive_strategies_every_minute())
    yield
    cleanup_task.cancel()


mcp = MCPServer('OpenCloning', instructions=INSTRUCTIONS, lifespan=lifespan)
