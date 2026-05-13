# opencloning-cli

`opencloning-cli` is the command-line companion to the OpenCloning backend. It is the preferred local workflow for seeding and resetting `opencloning-db` data.

The CLI is intentionally narrow. It does not manage production databases. It focuses on deterministic local DB state and stub generation.

## Install

`opencloning-cli` is a `uv` workspace member. From the repository root:

```bash
uv sync
uv run opencloning-cli --help
```

## Reset Local DB State

Use the top-level `db` commands for day-to-day local work:

```bash
uv run opencloning-cli db seed
uv run opencloning-cli db reset
```

For file-backed SQLite databases, `db reset` restores from a snapshot when one exists and otherwise seeds a new baseline. For non-file backends such as Postgres, `db reset` reseeds directly.

Snapshot commands remain SQLite-specific:

```bash
uv run opencloning-cli db snapshot create
uv run opencloning-cli db snapshot restore
```

## Generate DB Stubs

 Use `db stubs` to generate JSON stubs for frontend testing. By default it writes one JSON file per yielded stub request into `./stubs/db` (for example, `get_primers.json`, `get_sequences.json`, and similar request-specific files).

 The command resets the database to the default baseline and records the yielded stub requests as separate files in the output directory.

```bash
uv run opencloning-cli db stubs
```

Use `--output-dir` to override the destination folder:

```bash
uv run opencloning-cli db stubs --output-dir ./tmp/stubs
```
