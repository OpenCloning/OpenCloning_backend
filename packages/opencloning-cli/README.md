# opencloning-cli

`opencloning-cli` is the command-line companion to the OpenCloning backend. Its first iteration exists to support **Cypress-driven frontend testing**: spin up a seeded SQLite database, snapshot it, and reset it to that snapshot between tests.

The CLI is intentionally narrow. It does not talk to the API. It does not manage production databases. It only orchestrates files and DB seeding on the local filesystem.

## Install

`opencloning-cli` is a `uv` workspace member. From the repository root:

```bash
uv sync
uv run opencloning-cli --help
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
