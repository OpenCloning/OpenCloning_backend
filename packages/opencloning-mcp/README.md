# opencloning-mcp

A proof-of-concept [MCP](https://modelcontextprotocol.io) server that lets an AI assistant (Claude Code, Claude Desktop, VS Code...) build OpenCloning cloning strategies step by step: import sequences, run cloning operations, and export a strategy JSON that opens in the [OpenCloning web app](https://opencloning.org).

The one idea behind it: **the strategy lives on the server, and the model only passes integer ids.** The model never copies sequences between tool calls. It calls `start_strategy`, gets a `strategy_id`, and every import or cloning operation adds one sequence to that strategy and returns its id. The cloning itself is done by the OpenCloning cloning API (the `opencloning` package), which runs inside the same process.

## Running the server

From the repository root:

```bash
uv sync
uv run opencloning-mcp
```

The server listens on `http://localhost:8002/mcp` (Streamable HTTP). To reload the server when the code changes (strategies survive: they are in the database):

```bash
uv run uvicorn opencloning_mcp.server:app --factory --port 8002 --reload --reload-dir packages/opencloning-mcp/src
```

Strategies are stored in a SQLite file, `opencloning_mcp.sqlite`, in the working directory.

## Connecting an assistant

The server must already be running.

**Claude Code**:

```bash
# Only for you, in this project
claude mcp add --transport http -s local opencloning http://localhost:8002/mcp
# Or for everyone working on the repository (writes a .mcp.json you can commit)
claude mcp add --transport http -s project opencloning http://localhost:8002/mcp
```

Check it with `/mcp` inside Claude Code.

**VS Code** (`.vscode/mcp.json`):

```json
{
  "servers": {
    "opencloning": { "type": "http", "url": "http://localhost:8002/mcp" }
  }
}
```

**Claude Desktop** only launches local commands, so use [`mcp-remote`](https://www.npmjs.com/package/mcp-remote) as a bridge, in `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "opencloning": { "command": "npx", "args": ["mcp-remote", "http://localhost:8002/mcp"] }
  }
}
```

Then ask, for example: *"Start a cloning strategy. Import pFA6a-hphMX6 from this GenBank file, cut out the hphMX6 cassette with BamHI and SacI, PCR this gene with primers adding the same sites, and ligate it into the backbone. Give me the file at the end."* The assistant replies with a download link to the strategy JSON, which you can load in the web app.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `OPENCLONING_MCP_PORT` | `8002` | Port of the server. |
| `OPENCLONING_MCP_BASE_URL` | `http://localhost:<port>` | Public URL of the server, used in the download links. |
| `OPENCLONING_MCP_DB_URL` | `sqlite:///opencloning_mcp.sqlite` | SQLAlchemy URL of the strategy store. |
| `OPENCLONING_MCP_INACTIVITY_MINUTES` | `30` | Strategies unused for this long are deleted. |
| `ADDGENE_TOKEN` | – | Needed by `add_sequence_from_addgene` (a setting of the cloning API). |
| `NCBI_API_KEY` | – | Optional, raises the NCBI rate limit for `add_sequence_from_genbank`. |

The server also offers a `start` prompt (in Claude Code, `/mcp__opencloning__start`) that opens a session by explaining what it can do and how to give it files.

## Tools

Managing the strategy:

| Tool | What it does |
|---|---|
| `start_strategy` | Create an empty strategy and return its `strategy_id`. |
| `describe_strategy` | List the sequences and primers of the strategy, and how each sequence was made. |
| `rename_sequence` | Rename a sequence. |
| `get_strategy_json` | Return a download link to the strategy JSON. |
| `get_upload_link` | Return a link to a web page where the user uploads one or more sequence files (including SnapGene `.dna`) without them going through the model. The first sequence of each file is added. |

Adding sequences and primers:

| Tool | What it does |
|---|---|
| `add_sequence_from_path` | Read a sequence file (including SnapGene `.dna`) from a path on the computer where the server runs. Nothing goes through the model. |
| `add_sequence_from_file` | Read the text of a GenBank, FASTA or EMBL file, retyped by the model. |
| `add_typed_sequence` | A sequence typed as DNA letters. |
| `add_sequence_from_genbank` | Import from NCBI by accession. |
| `add_sequence_from_addgene` | Import from Addgene by id (needs `ADDGENE_TOKEN`). |
| `add_primer` | Add a primer (also used for oligos and CRISPR guides). |

Genome regions from NCBI (the "Genome region" source of the web app). The first three only look things up, and add nothing to the strategy:

| Tool | What it does |
|---|---|
| `find_genome_assembly` | From a species name, taxon id or assembly id, find the assembly (the reference one for a species) and whether it has gene annotation. |
| `find_gene` | Search the genes of an annotated assembly. |
| `list_assembly_chromosomes` | List the sequence accessions of an assembly. |
| `add_genome_region_from_gene` | Add a gene with upstream / downstream flanking bases (relative to the gene's strand, oriented as the gene). |
| `add_genome_region_from_coordinates` | Add a region by sequence accession and coordinates. |

Cloning operations. When an operation has several possible products, the tool returns them as `"choose_product"` candidates and adds nothing. The model then calls it again with `product_index`.

| Tool | Cloning API endpoint |
|---|---|
| `restriction_digest` | `/restriction` |
| `pcr` | `/pcr` |
| `ligation` | `/ligation` |
| `restriction_and_ligation` (incl. Golden Gate) | `/restriction_and_ligation` |
| `gibson_assembly` | `/gibson_assembly` |
| `in_fusion` | `/gibson_assembly` |
| `in_vivo_assembly` | `/gibson_assembly` |
| `overlap_extension_pcr` | `/gibson_assembly` |
| `homologous_recombination` | `/homologous_recombination` |
| `crispr_hdr` | `/crispr` |
| `gateway` (BP and LR) | `/gateway` |
| `list_gateway_sites` (read-only) | `/annotation/get_gateway_sites` |
| `cre_lox_recombination` | `/cre_lox_recombination` |
| `polymerase_extension` | `/polymerase_extension` |
| `reverse_complement` | `/reverse_complement` |
| `oligo_hybridization` | `/oligonucleotide_hybridization` |

## Development

```bash
# Tests (in-memory MCP client, temporary SQLite database)
uv run pytest packages/opencloning-mcp/tests

# End-to-end walkthrough against a running server, over HTTP. It saves the resulting strategy
# to scripts/smoke_strategy.json, to load in the web app
uv run python packages/opencloning-mcp/scripts/smoke.py http://localhost:8002/mcp
```

To check the exported strategy in the web app, serve it with `SERVE_FRONTEND=1 uv run uvicorn opencloning.main:app --port 8000` and load the JSON at `http://localhost:8000`.

[evals.md](./evals.md) lists tasks to try with a real model driving the tools.

The code is short and flat. Every cloning tool is a call to `run_operation()` in `tools_operations.py`. `storage.py` holds the strategy and the id rules, and `app.py` holds the instructions the model reads when it connects.

## Limitations

This is a proof of concept for localhost use:

- `add_sequence_from_path` only works when the server runs on the same computer as the assistant, and it can read any sequence file the server can. With `add_sequence_from_file`, the model retypes the file contents as a string argument: fine for small text files, impossible for binary ones. For those, `get_upload_link` gives the user an upload page instead. That page only adds the first sequence of each file, has no error handling, and the user has to tell the model when the upload is done.
- The `strategy_id` appears in the transcript and works as a bearer secret: anyone who has it can read and modify the strategy. There is no authentication.
- A strategy is deleted after 30 minutes without use, so unexported work is lost. The model is told to offer the download link at the end of each task.
- Choosing a product re-runs the operation, which assumes the cloning API returns candidates in a stable order.
- Names longer than 16 characters widen the GenBank LOCUS line. This is harmless (round-trip verified).
- Only one server process: the store uses SQLite and a process-local lock.
- The download link needs the server to be reachable from the browser (forward the port in a dev container).
- No stdio transport: the download links are served by the HTTP app.
- The genome tools need network access to NCBI, and a gene search only returns the first page of NCBI results.
- Not supported yet: primer design, `/recombinase`, the other repository importers, SnapGene history import, Sanger alignment and batch cloning.
