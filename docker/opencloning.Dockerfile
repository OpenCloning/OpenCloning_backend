# Backend for OpenCloning
# https://github.com/OpenCloning/OpenCloning_backend
#
# Production (cloning app): docker build -f docker/opencloning.Dockerfile .
# Production (db combined): docker build -f docker/opencloning.Dockerfile --build-arg APP_TARGET=db .
# CI tests:                docker build -f docker/opencloning.Dockerfile --target builder-test .

ARG APP_TARGET="cloning"

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
FROM workspace-opencloning AS builder-prod-cloning

RUN uv sync --frozen --package opencloning --no-default-groups --no-editable

# Workspace + opencloning-db (for CI / full workspace test sync)
FROM workspace-opencloning AS workspace-full

COPY packages/opencloning-db/pyproject.toml packages/opencloning-db/
COPY packages/opencloning-db/README.md packages/opencloning-db/
COPY packages/opencloning-db/src packages/opencloning-db/src
COPY packages/opencloning-cli packages/opencloning-cli

FROM workspace-full AS builder-test

RUN uv sync --frozen --no-default-groups --no-editable --group test

ENV PATH="/usr/local/bin/mafft/bin:$VIRTUAL_ENV/bin:$PATH"

COPY packages/opencloning-db/tests packages/opencloning-db/tests
COPY packages/opencloning/tests packages/opencloning/tests

FROM workspace-full AS builder-prod-db

ENV VIRTUAL_ENV="/home/backend/venv"
ENV UV_PROJECT_ENVIRONMENT=$VIRTUAL_ENV
RUN uv sync --frozen --package opencloning-db --package opencloning-cli --no-default-groups --no-editable

FROM builder-prod-${APP_TARGET} AS builder-selected

# FINAL IMAGE (default build target)
FROM python:3.12-alpine3.21 AS production

# You need bash to run mafft and runtime libraries for MARS
RUN apk update --no-cache && apk add --no-cache bash libstdc++ libgomp libgcc

# create a user to run the app
RUN adduser -s /bin/bash -D backend
USER backend
WORKDIR /home/backend
ARG APP_TARGET="cloning"
ENV APP_TARGET="${APP_TARGET}"

ENV VIRTUAL_ENV="/home/backend/venv"
COPY --from=builder-selected $VIRTUAL_ENV $VIRTUAL_ENV
COPY --from=builder-selected /usr/local/bin/mars /usr/local/bin/mars
COPY --from=builder-selected /usr/local/bin/mafft /usr/local/bin/mafft

ENV PATH="/usr/local/bin/mafft/bin:$VIRTUAL_ENV/bin:$PATH"
ENV USE_HTTPS=false

# Worker processes per container
ENV WEB_CONCURRENCY=2

COPY ./docker/docker_entrypoint.sh ./docker_entrypoint.sh

CMD ["bash", "./docker_entrypoint.sh"]
