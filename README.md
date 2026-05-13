[![Python tests](https://github.com/OpenCloning/OpenCloning_backend/actions/workflows/ci.yml/badge.svg)](https://github.com/OpenCloning/OpenCloning_backend/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/OpenCloning/OpenCloning_backend/graph/badge.svg?token=CFIB2H6WMO)](https://codecov.io/gh/OpenCloning/OpenCloning_backend)

# OpenCloning Backend API

This API is part of a bigger application, before going further, please go to the [main project readme](https://github.com/OpenCloning/OpenCloning), where you can find an introduction.

This python API is built with [FastAPI](https://fastapi.tiangolo.com/) and is for *in silico* cloning.

## Summary

Read [main project readme](https://github.com/OpenCloning/OpenCloning) first.

This API provides a series of entry points. The API documentation can be accessed [here](https://api.opencloning.org/docs). You can use the documentation page to try some request directly on the browser. Otherwise, the API is open for you to make requests from a python script or command line at: [https://api.opencloning.org/](https://api.opencloning.org/).

## Scripting with pydna

You can write python scripts to automate cloning using the python library [pydna](https://github.com/pydna-group/pydna), which is now integrated with the OpenCloning data model. See [the documentation](https://github.com/pydna-group/pydna/blob/master/docs/notebooks/history.ipynb) for how to get started.

## Migrating between model versions and fixing model bugs

* The data model changes, so the json files you created may not be compatible with the newest version of the library, which uses the latest data mode. You can easily fix this using `python -m opencloning_linkml.migrations.migrate file.json
` see [full documentation](https://github.com/OpenCloning/OpenCloning_LinkML?tab=readme-ov-file#migration-from-previous-versions-of-the-schema).
* Before version 0.3, there was a bug for assembly fields that included locations spanning the origin. See the details and how to fix it in the documentation of [this file](./packages/opencloning/src/opencloning/bug_fixing/README.md).

## Getting started

If you want to quickly set up a local instance of the frontend and backend of the application, check [getting started in 5 minutes](https://github.com/OpenCloning/OpenCloning#timer_clock-getting-started-in-5-minutes) in the main repository.

### Running locally

You can install this as a python package:

```bash
# Create a virtual environment
python -m venv .venv
# Activate the virtual environment
source .venv/bin/activate
# Install the package from pypi
pip install opencloning
# Run the API (uvicorn should be installed in the virtual environment)
uvicorn opencloning.main:app
```

### Installing from GitHub (monorepo)

This repository is a uv workspace; the installable package lives in `packages/opencloning/`.
When installing directly from GitHub, include the `subdirectory` fragment:

```bash
# uv
uv add "opencloning @ git+https://github.com/OpenCloning/OpenCloning_backend.git@master#subdirectory=packages/opencloning"

# pip
pip install "git+https://github.com/OpenCloning/OpenCloning_backend.git@master#subdirectory=packages/opencloning"
```

### Running locally if you want to contribute

This repository is a [uv](https://docs.astral.sh/uv/) workspace: the installable package lives under `packages/opencloning/`, and the repo root holds workspace metadata and shared dev dependencies. Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then from the repository root:

```bash
# Install the workspace (editable opencloning + dev/test dependency groups) into .venv
uv sync

# Install the pre-commit hooks
uv run pre-commit install

# Run tools via uv, or activate .venv and use them directly
source .venv/bin/activate   # optional
```

The virtual environment is created at the repository root (`.venv`). For VS Code settings see the folder `.vscode`.

Now you should be able to run the api by running:

```bash
# The --reload argument will reload the API if you make changes to the code
uvicorn opencloning.main:app --reload --reload-exclude='.venv'
```

Then you should be able to open the API docs at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) to know that your API is working.

### Running locally with docker :whale:

If you want to serve the full site (backend and frontend) with docker, check [getting started in 5 minutes](https://github.com/OpenCloning/OpenCloning#timer_clock-getting-started-in-5-minutes) in the main repository.

If you want to serve only the backend from a docker container, an image is available at [manulera/opencloningbackend](https://hub.docker.com/r/manulera/opencloningbackend). The image is built from [`docker/opencloning.Dockerfile`](docker/opencloning.Dockerfile) (repository root as build context) and exposes the port 3000. To run it:

```bash
docker build -f docker/opencloning.Dockerfile -t manulera/opencloningbackend .
docker run -d --name backendcontainer -p 8000:8000 manulera/opencloningbackend

```

To run with a read-only root filesystem while still allowing temporary files (required for tools like mafft), mount `/tmp` as tmpfs (RAM-backed writable storage). This will not work with `RECORD_STUBS=1` (see [Generating API stubs](#generating-api-stubs)).

```bash
docker run -d --name backendcontainer -p 8000:8000 \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=256M \
  manulera/opencloningbackend
```

If you want to build the test image locally, you can do so by:

```bash
docker build -f docker/opencloning.Dockerfile -t manulera/opencloningbackend-test --target builder-test .
```

If you don't want to download the repository and build the image, you can fetch the latest image from dockerhub.

```bash
docker pull manulera/opencloningbackend
docker run -d --name backendcontainer -p 8000:8000 manulera/opencloningbackend
```

The api will be running at `http://localhost:8000`, so you should be able to access the docs at [http://localhost:8000/docs](http://localhost:8000/docs).

### Connecting to the frontend

If you want to receive requests from the [frontend](https://github.com/OpenCloning/OpenCloning_frontend), or from another web application you may have to include the url of the frontend application in the CORS exceptions. By default, if you run the dev server with `uvicorn opencloning.main:app --reload --reload-exclude='.venv'`, the backend will accept requests coming from `http://localhost:3000`, which is the default address of the frontend dev server (ran with `yarn start`).

If you want to change the allowed origins, you can do so via env variables (comma-separated). e.g.:

```
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:3001 uvicorn opencloning.main:app --reload --reload-exclude='.venv'
```

Similarly, the frontend should be configured to send requests to the backend address, [see here](https://github.com/OpenCloning/OpenCloning_frontend#connecting-to-the-backend).

#### Serving the frontend from the backend

You may prefer to handle everything from a single server. You can do so by:
* Build the [frontend](https://github.com/OpenCloning/OpenCloning_frontend) with `yarn build`.
* Copy the folder `build` from the frontend to the root directory of the backend, and rename it to `frontend`.
* Set the environment variable `SERVE_FRONTEND=1` when running the backend. By default this will remove all allowed origins, but you can still set them with `ALLOWED_ORIGINS`.
* Set the value of `backendUrl` in `frontend/config.js` to `/`.
* Now, when you go to the root of the backend (e.g. `http://localhost:8000`), you should receive the frontend instead of the greeting page of the API.

You can see how this is done in this [docker image](https://github.com/OpenCloning/OpenCloning/blob/master/Dockerfile) and [docker-compose file](https://github.com/OpenCloning/OpenCloning/blob/master/docker-compose.yml).

## Contributing :hammer_and_wrench:

Check [contribution guidelines in the main repository](https://github.com/OpenCloning/OpenCloning/blob/master/CONTRIBUTING.md) for general guidelines.

For more specific tasks:
* Creating a new type of source: follow the [new source issue template](.github/ISSUE_TEMPLATE/new-source.md). You can create an issue like that [here](https://github.com/OpenCloning/OpenCloning_backend/issues/new?assignees=&labels=new-source&projects=&template=new-source.md&title=New+source%3A+%3Cname-of-source%3E).

## Running the tests locally

From the repository root (after `uv sync`):

```bash
uv run pytest packages/opencloning/tests -v -ks
```

## Running opencloning-db locally

`opencloning-db` is a companion API/database service for OpenCloning data workflows. It now lives in `packages/opencloning-db/src` and uses the local workspace `opencloning` package.
This is currently an experimental feature, so behavior and interfaces may change.
For a package-specific quickstart (what it is and how to run it), see [`packages/opencloning-db/README.md`](./packages/opencloning-db/README.md).

From the repository root:

```bash
# Install/update workspace dependencies
uv sync

# Start local Postgres with dev/test/e2e databases
docker compose -f docker/docker-compose.db.yml up -d

# Load required local runtime config
source .env.dev

# Run opencloning-db tests
uv run pytest packages/opencloning-db/tests -v

# Recreate the opencloning-db local database seed
uv run opencloning-cli db seed

# Run the opencloning-db API
uv run uvicorn opencloning_db.api:app --port 8001 --reload --reload-exclude='.venv'
```

If you need to run the init script manually:

```bash
uv run --directory packages/opencloning-db/src python -m opencloning_db.init_db
```

`.env.dev` is the canonical local defaults file for host-side development. Load it before running `opencloning-cli`, `opencloning-db`, or local backend tests.

`opencloning-cli db seed` is the preferred local workflow for recreating the baseline database and file directories.

The DB-only compose file creates `opencloning_dev`, `opencloning_test`, and `opencloning_e2e` on first startup so local development, tests, and E2E work can stay separated.

## Dependency guardrail (deptry)

This repository uses a uv workspace. In a workspace, dependencies are resolved in one shared environment, so imports can appear to work even when a package does not declare them in its own `pyproject.toml`.

To catch that, pre-commit runs `deptry` separately for `opencloning` and `opencloning-db`, each using that package’s `pyproject.toml` as the source of truth for declared dependencies.

Run them manually from the repository root:

```bash
uv run deptry --config packages/opencloning/pyproject.toml packages/opencloning/src
uv run deptry --config packages/opencloning-db/pyproject.toml packages/opencloning-db/src
```

Current rollout note: known undeclared imports such as `pydna` are temporarily ignored and should be removed from the ignore list once dependencies are declared.

## Addgene authenticated access

Addgene now requires authenticated access to retrieve sequence files.

To be able to access AddGene sequences, create an account on AddGene and set these environment variables to enable Addgene imports:

```bash
export ADDGENE_USERNAME="your_addgene_username"
export ADDGENE_PASSWORD="your_addgene_password"
```

For one-off local runs you can also prefix commands:

```bash
ADDGENE_USERNAME="your_addgene_username" ADDGENE_PASSWORD="your_addgene_password" uv run pytest packages/opencloning/tests -v -ks
```

If these variables are not set, Addgene import endpoints return an informative error explaining that credentials are required.

Use of Addgene credentials and data must comply with Addgene Terms of Use.

For CI, configure repository secrets named `ADDGENE_USERNAME` and `ADDGENE_PASSWORD` so Addgene-dependent tests can run.

## Notes

### Pin a particular library version from GitHub

Do not do the default:

```
uv add git+https://github.com/pydna-group/pydna --branch main
uv add git+https://github.com/pydna-group/pydna --rev 4fd760d075f77cceeb27969e017e04b42f6d0aa3
```

Instead, edit pyproject directly:

```
pydna @ git+https://github.com/pydna-group/pydna@fa00f2a1240bd2caae7a89c808a464f297209ecf
```

The reason for this is that otherwise you cannot install the package from pip from the repository,
as the github version is not pinned. For the same reasons, you don't want to publish this to pypi,
and this will make the action fail.

If resolution seems stale, clear uv’s cache:

```bash
uv cache clean
```

### Generating API stubs

For the frontend, it may be useful to produce stubs (I use them for writing the tests). See how this is implemented
by looking at the `RecordStubRoute` class in `api_config_utils.py`. To run the dev server and record stubs:

```bash
RECORD_STUBS=1 uvicorn opencloning.main:app --reload --reload-exclude='.venv'
```

This will record the stubs (requests and responses) in the `stubs` folder.


### Catalogs

Catalogs are used to map ids to urls for several plasmid collections. They are stored under `packages/opencloning/src/opencloning/catalogs/`.

To update the catalogs, run the following command from the repository root:

```bash
uv run python scripts/update_catalogs.py
```
