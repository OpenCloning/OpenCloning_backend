# opencloning-cli

`opencloning-cli` is the command-line companion to the OpenCloning backend. It provides safe schema initialization plus guarded local seeding and stub workflows for `opencloning-db`.

The CLI is intentionally narrow. It focuses on schema initialization plus deterministic local/test DB state and stub generation.

## Install

`opencloning-cli` is a `uv` workspace member. From the repository root:

```bash
uv sync
uv run opencloning-cli --help
```

## Initialize Schema

Use `db init` to create the configured schema without dropping existing tables or rewriting object storage.

```bash
source .env.dev
uv run opencloning-cli db init
```

## Seed Local DB State

`db seed` is destructive. It recreates the Postgres baseline and rebuilds the `sequence_files` and `sequencing_files` directories from scratch. To make accidental data loss harder, it only runs when `OPENCLONING_TESTING=1`.

Use it explicitly when you want the deterministic demo/test baseline:

```bash
source .env.dev
OPENCLONING_TESTING=1 uv run opencloning-cli db seed
```

## Generate DB Stubs

 Use `db stubs` to generate JSON stubs for frontend testing. By default it writes one JSON file per yielded stub request into `./stubs/db` (for example, `get_primers.json`, `get_sequences.json`, and similar request-specific files).

 The command reseeds the database to the default baseline between stub cases and records the yielded stub requests as separate files in the output directory. Like `db seed`, it requires `OPENCLONING_TESTING=1`.

```bash
OPENCLONING_TESTING=1 uv run opencloning-cli db stubs
```

Use `--output-dir` to override the destination folder:

```bash
uv run opencloning-cli db stubs --output-dir ./tmp/stubs
```
