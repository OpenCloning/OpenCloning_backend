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

# Point opencloning-db at your local Postgres instance
export OPENCLONING_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/opencloning_dev'

# Optional: use dedicated databases for tests or E2E work
# export OPENCLONING_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/opencloning_test'
# export OPENCLONING_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/opencloning_e2e'

# Seed or reset the local baseline
uv run opencloning-cli db reset

# Run the opencloning-db API
uv run uvicorn opencloning_db.api:app --port 8001 --reload --reload-exclude='.venv'
```

If startup succeeds, the API docs should be available at [http://127.0.0.1:8001/docs](http://127.0.0.1:8001/docs).

`OPENCLONING_DATABASE_URL` also accepts SQLite URLs. For Postgres-backed local development, the CLI `db reset` command reseeds the database directly. Snapshot create/restore commands are still limited to file-backed SQLite databases.

The DB-only compose file creates these local databases automatically on first startup:

- `opencloning_dev`
- `opencloning_test`
- `opencloning_e2e`

## Related local workflows

For test and database seed commands, see the repository root [README](../../README.md#running-opencloning-db-locally).
