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

# Returned by start_strategy for the model to pass on to the user
FILE_TIP = (
    "Tip: don't paste sequence files into the chat, it is slow and uses up your usage. Tell me where the file "
    'is on your computer (or drag it into Claude Code, which gives me its path), or ask for an upload link.'
)

# Sent to the model when it connects: how to use the tools together
INSTRUCTIONS = f"""
This server builds OpenCloning cloning strategies step by step. The strategy is stored on the server:
you never pass sequences around, you refer to sequences and primers by the integer ids the tools return.

Workflow:
1. Call start_strategy once and keep the returned strategy_id. Pass it to every other tool.
2. Add the starting sequences with the add_sequence_* tools, and primers with add_primer.
   Each returns the id of the new sequence or primer.
   To take a gene or a region from a genome: find_genome_assembly (species -> reference assembly), find_gene,
   then add_genome_region_from_gene (with flanking bases); or add_genome_region_from_coordinates. Never
   guess an assembly or a gene when several match: ask the user.
3. Run cloning operations (restriction digest, PCR, ligation, assemblies...) on those ids.
   Each operation adds exactly one new sequence to the strategy and returns its id.
   Besides those, there are Gateway (BP/LR), Cre-lox, homologous recombination, CRISPR HDR, oligo
   hybridization, polymerase extension and reverse complement.
4. If a tool returns status "choose_product", nothing was added yet: pick the candidate that matches what
   the user wants (ask the user if it is not clear) and call the same tool again with product_index.
5. Call describe_strategy to see every sequence in the strategy and how it was made.
6. When the user is done, call get_strategy_json and give them the download link. The file opens in
   the OpenCloning web app.

Files: users often drop or paste sequence files in the chat. Retyping a file as an argument is slow, uses up
the user's usage, and is impossible for binary files (SnapGene .dna). So:
- If you have the path of a file on the user's computer, use add_sequence_from_path.
- Otherwise, for a short text file (GenBank, FASTA, EMBL) use add_sequence_from_file.
- For binary files, or any long file you only have as text, call get_upload_link and tell the user plainly:
  "I can't read files dropped in the chat, please upload them here", then wait for them to say it is done.
- When you start a strategy, pass on the tip returned in `tell_the_user` to the user, in your own words.

Naming: every tool that creates a sequence takes an optional `name`, pass one so that the user can
recognise the sequences. The conventions are:
- An intermediate product: the name of the parent sequence plus what was done to it, e.g.
  "pFA6a-hphMX6_BamHI_SacI" for a restriction fragment, or "GFP_pcr" for a PCR product.
- A plasmid or construct that the user will keep: name it as a researcher would, e.g. "pFA6a-GFP".
- Names cannot contain whitespace (they go into a GenBank file): use underscores or hyphens, and keep
  them under 40 characters.
When you don't pass a name, one is derived from the parent sequence and the operation. Tell the user
which name you gave to a construct they will keep, and call rename_sequence if they prefer another one.

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
