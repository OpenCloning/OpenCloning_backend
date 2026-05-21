# opencloning-db

`opencloning-db` is the database/API companion package for the OpenCloning backend. It provides the app and local data workflows used for OpenCloning database features.

## Run locally

From the repository root:

```bash
# Install or update workspace dependencies
uv sync

# If you are using mac, you may have to stop any local Postgres instances running on port 5432
brew services stop postgresql

# Start local Postgres with dev/test/e2e databases plus Garage for object storage
docker compose \
    -f docker/docker-compose.postgres.yml \
    -f docker/docker-compose.garage.yml \
    up -d postgres garage

# Load required local runtime config
source .env.dev

# Create the schema safely
uv run opencloning-cli db init

# Optional: load the deterministic demo/test baseline
OPENCLONING_TESTING=1 uv run opencloning-cli db seed

# Run both the cloning and the database API - this what the OpenCloningDB frontend expects
uv run uvicorn opencloning_db.combined:app --reload --reload-exclude='.venv'

# Run the opencloning-db API (only database, not cloning. This is not used when running with the frontend)
uv run uvicorn opencloning_db.api:app --reload --reload-exclude='.venv'
```

That will serve the cloning API at [http://127.0.0.1:8000/cloning](http://127.0.0.1:8000/cloning) and the database API at [http://127.0.0.1:8001/db](http://127.0.0.1:8001/db). That's what the OpenCloningDB frontend expects.

When the cloning app is served through `opencloning_db.combined`, the entire `/cloning` mount is protected by the same bearer-token authentication used by the db API.

## Running tests locally

From the repository root:

```bash
# Install or update workspace dependencies
uv sync

# Run the tests
uv run pytest packages/opencloning-db/tests -v -ks
```

## Frontend testing

Frontend testing using the database requires reseeding after tests that modify the database. You can do this by calling the `/__test/reset-db` endpoint with the `X-Test-Reset-Token` header set to `RESET-TOKEN`. That endpoint is only available if the `OPENCLONING_TESTING` environment variable is set to `1`, and it delegates to the guarded `opencloning-cli db seed` command.

## Building and running the Docker image

The Dockerfile is shared with the cloning app, and the build arg `APP_TARGET` determines which app to build. So you can build the image by running:

```bash
docker build -f docker/opencloning.Dockerfile --build-arg APP_TARGET=db -t manulera/opencloning-db-backend .
```

Then run it for development:

```bash
# Run the containers (Postgres + Garage + db API)
docker compose \
    -f docker/docker-compose.postgres.yml \
    -f docker/docker-compose.garage.yml \
    -f docker/docker-compose.opencloning-db.yml \
    up -d
```

That stack exposes Garage's S3-compatible API at [http://127.0.0.1:9000](http://127.0.0.1:9000). Garage does not provide a MinIO-style browser console in this setup, so use an S3 client such as `awscli` or `mc` if you need to inspect the local bucket. The local defaults in `.env.dev` point host-side `uv run ...` commands at the same Garage bucket used by the containerized db API.
