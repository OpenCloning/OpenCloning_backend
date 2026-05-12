# Backend for OpenCloning
# https://github.com/OpenCloning/OpenCloning_backend
#
# Production: docker build -f docker/opencloning.Dockerfile .
# CI tests:    docker build -f docker/opencloning.Dockerfile --target builder-test .

# BUILDER — shared setup
FROM manulera/opencloningbackend-base:python_3.12-alpine3.21 AS base-setup

RUN adduser -s /bin/bash -D backend
USER backend
WORKDIR /home/backend

ENV PIP_DISABLE_PIP_VERSION_CHECK=on
ENV UV_COMPILE_BYTECODE=1

ENV VIRTUAL_ENV="/home/backend/venv"
ENV UV_PROJECT_ENVIRONMENT=$VIRTUAL_ENV
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

RUN pip install --no-cache-dir uv

# Workspace: opencloning only (enough for prod lock sync)
FROM base-setup AS workspace-opencloning

COPY pyproject.toml uv.lock ./
COPY packages/opencloning/pyproject.toml packages/opencloning/README.md packages/opencloning/
COPY packages/opencloning/src packages/opencloning/src

# Production venv — only opencloning + runtime deps
FROM workspace-opencloning AS builder-prod

ARG PACKAGE_VERSION="0.1.0"
ENV SETUPTOOLS_SCM_PRETEND_VERSION="${PACKAGE_VERSION}"

RUN uv sync --frozen --package opencloning --no-default-groups --no-editable

# Workspace + opencloning-db (for CI / full workspace test sync)
FROM workspace-opencloning AS workspace-full

COPY packages/opencloning-db/pyproject.toml packages/opencloning-db/
COPY packages/opencloning-db/README.md packages/opencloning-db/
COPY packages/opencloning-db/src packages/opencloning-db/src

FROM workspace-full AS builder-test

ARG PACKAGE_VERSION="0.1.0"
ENV SETUPTOOLS_SCM_PRETEND_VERSION="${PACKAGE_VERSION}"

COPY packages/opencloning-cli packages/opencloning-cli

RUN uv sync --frozen --no-default-groups --no-editable --group test

ENV PATH="/usr/local/bin/mafft/bin:$VIRTUAL_ENV/bin:$PATH"

COPY packages/opencloning-db/tests packages/opencloning-db/tests
COPY packages/opencloning/tests packages/opencloning/tests

# FINAL IMAGE (default build target)
FROM python:3.12-alpine3.21 AS production

# You need bash to run mafft and runtime libraries for MARS
RUN apk update --no-cache && apk add --no-cache bash libstdc++ libgomp libgcc

# create a user to run the app
RUN adduser -s /bin/bash -D backend
USER backend
WORKDIR /home/backend

ENV VIRTUAL_ENV="/home/backend/venv"
COPY --from=builder-prod $VIRTUAL_ENV $VIRTUAL_ENV
COPY --from=builder-prod /usr/local/bin/mars /usr/local/bin/mars
COPY --from=builder-prod /usr/local/bin/mafft /usr/local/bin/mafft

ENV PATH="/usr/local/bin/mafft/bin:$VIRTUAL_ENV/bin:$PATH"
# For example, ROOT_PATH="/syc"
ENV ROOT_PATH=""
ENV USE_HTTPS=false

COPY ./docker_entrypoint.sh ./docker_entrypoint.sh

CMD ["sh", "./docker_entrypoint.sh"]
