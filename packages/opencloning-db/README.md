# opencloning-db

`opencloning-db` is the database/API companion package for the OpenCloning backend. It provides the app and local data workflows used for OpenCloning database features.

## Run locally

From the repository root:

```bash
# Install or update workspace dependencies
uv sync

# If you are using mac, you may have to stop any local Postgres instances running on port 5432
brew services stop postgresql

# Start local Postgres with dev/test/e2e databases
docker compose -f docker/docker-compose.db.yml up -d

# Load required local runtime config
source .env.dev

# Seed the local baseline
uv run opencloning-cli db seed

# Run the opencloning-db API
uv run uvicorn opencloning_db.api:app --port 8001 --reload --reload-exclude='.venv'
```

If startup succeeds, the API docs should be available at [http://127.0.0.1:8001/docs](http://127.0.0.1:8001/docs).

The required runtime config lives in `.env.dev` for local development. Load it before running the CLI or API on the host.

`OPENCLONING_DATABASE_URL` should point at Postgres. For local development, `opencloning-cli db seed` recreates the database baseline from scratch.

Use `OPENCLONING_DATABASE_URL` for the runtime database and `OPENCLONING_TEST_DATABASE_URL` for Postgres-backed test runs when you want to override the default test database.

The DB-only compose file creates these local databases automatically on first startup:

- `opencloning_dev`
- `opencloning_test`
- `opencloning_e2e`

## Related local workflows

For test and database seed commands, see the repository root [README](../../README.md#running-opencloning-db-locally).
