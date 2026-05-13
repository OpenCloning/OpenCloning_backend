# opencloning-cli

`opencloning-cli` is the command-line companion to the OpenCloning backend. It is the preferred local workflow for seeding `opencloning-db` data and generating DB stubs.

The CLI is intentionally narrow. It does not manage production databases. It focuses on deterministic local DB state and stub generation.

## Install

`opencloning-cli` is a `uv` workspace member. From the repository root:

```bash
uv sync
uv run opencloning-cli --help
```

## Seed Local DB State

Use the top-level `db` commands for day-to-day local work:

```bash
source .env.dev
uv run opencloning-cli db seed
```

`db seed` recreates the Postgres baseline and rebuilds the `sequence_files` and `sequencing_files` directories from scratch.

## Generate DB Stubs

 Use `db stubs` to generate JSON stubs for frontend testing. By default it writes one JSON file per yielded stub request into `./stubs/db` (for example, `get_primers.json`, `get_sequences.json`, and similar request-specific files).

 The command reseeds the database to the default baseline between stub cases and records the yielded stub requests as separate files in the output directory.

```bash
uv run opencloning-cli db stubs
```

Use `--output-dir` to override the destination folder:

```bash
uv run opencloning-cli db stubs --output-dir ./tmp/stubs
```
