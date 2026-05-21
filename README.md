[![Python tests](https://github.com/OpenCloning/OpenCloning_backend/actions/workflows/ci.yml/badge.svg)](https://github.com/OpenCloning/OpenCloning_backend/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/OpenCloning/OpenCloning_backend/graph/badge.svg?token=CFIB2H6WMO)](https://codecov.io/gh/OpenCloning/OpenCloning_backend)

# OpenCloning Backend monorepo

This monorepo contains the backend API and the database API. Before going further, please check out the [project website](https://opencloning.org) and read the [main project readme](https://github.com/OpenCloning/OpenCloning).

This repository contains two main packages and a CLI that are part of the OpenCloning project. Check out their respective readmes for more information on how to run them locally or using Docker:
- [opencloning](./packages/opencloning/README.md): the backend API for *in silico* cloning
- [opencloning-db](./packages/opencloning-db/README.md): the database API to store a collection of plasmids, primers, and lines.
- [opencloning-cli](./packages/opencloning-cli/README.md): useful CLI for development and testing.

## Running the cloning API locally - for the OpenCloning frontend

From the repository root:

```bash
# Install or update workspace dependencies
uv sync
# Run the cloning API
uv run uvicorn opencloning.main:app --reload --reload-exclude='.venv'
```

## Running both the cloning and the database API locally - for the OpenCloningDB frontend

From the repository root:

```bash
# Install or update workspace dependencies
uv sync
# Load required local runtime config
source .env.dev
# If you are using mac, you may have to stop any local Postgres instances running on port 5432
brew services stop postgresql
# Start local Postgres with dev/test/e2e databases
docker compose -f docker/docker-compose.postgres.yml up -d
# Create the schema safely
uv run opencloning-cli db init
# Optional: load the deterministic demo/test baseline
OPENCLONING_TESTING=1 uv run opencloning-cli db seed
# Run the database API
uv run uvicorn opencloning_db.combined:app --reload --reload-exclude='.venv'
```

That will serve the cloning API at [http://127.0.0.1:8000/cloning](http://127.0.0.1:8000/cloning) and the database API at [http://127.0.0.1:8001/db](http://127.0.0.1:8001/db).

## Dependency guardrail (deptry)

This repository uses a uv workspace. In a workspace, dependencies are resolved in one shared environment, so imports can appear to work even when a package does not declare them in its own `pyproject.toml`.

To catch that, pre-commit runs `deptry` separately for `opencloning` and `opencloning-db`, each using that package’s `pyproject.toml` as the source of truth for declared dependencies.

Run them manually from the repository root:

```bash
uv run deptry --config packages/opencloning/pyproject.toml packages/opencloning/src
uv run deptry --config packages/opencloning-db/pyproject.toml packages/opencloning-db/src
```

## Scripting with pydna

You can write python scripts to automate cloning using the python library [pydna](https://github.com/pydna-group/pydna), which is now integrated with the OpenCloning data model. See [the documentation](https://github.com/pydna-group/pydna/blob/master/docs/notebooks/history.ipynb) for how to get started.

## Contributing :hammer_and_wrench:

Check [contribution guidelines in the main repository](https://github.com/OpenCloning/OpenCloning/blob/master/CONTRIBUTING.md) for general guidelines.

For more specific tasks:
* Creating a new type of source: follow the [new source issue template](.github/ISSUE_TEMPLATE/new-source.md). You can create an issue like that [here](https://github.com/OpenCloning/OpenCloning_backend/issues/new?assignees=&labels=new-source&projects=&template=new-source.md&title=New+source%3A+%3Cname-of-source%3E).

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
