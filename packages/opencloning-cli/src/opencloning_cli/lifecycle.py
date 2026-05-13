"""DB test lifecycle primitives.

These functions are pure library code (no Typer or click imports) so they can
be unit-tested directly against a ``Config`` pointing at a temporary
workspace.
"""

from __future__ import annotations

import io
import json
import base64
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

import opencloning_db.db as _db_module
from opencloning_db.config import Config, get_config
from opencloning_db.init_db import init_db as _init_db
from opencloning_db.api import app
from fastapi.testclient import TestClient
from .stubs import stubs, RecordedStub, StubRequest, StubResponse


def _dispose_engine() -> None:
    """Dispose any cached SQLAlchemy engine before reset or stub generation.

    ``opencloning_db.db`` caches a module-level engine keyed by URL; leaving
    it open risks stale connections after reseeding.
    """
    if _db_module._engine is not None:
        _db_module._engine.dispose()
        _db_module._engine = None
        _db_module._bound_database_url = None


def _reset_tree(path: Path) -> None:
    """Replace *path* with an empty directory."""
    if path.exists():
        import shutil

        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def seed(config: Config) -> None:
    """Run ``opencloning_db.init_db.init_db`` against *config*.

    Recreates a deterministic database baseline plus fresh sequence and
    sequencing file directories for the configured backend.
    """
    _dispose_engine()
    _reset_tree(Path(config.sequence_files_dir))
    _reset_tree(Path(config.sequencing_files_dir))
    # ``init_db`` prints a success message; keep CLI successful runs silent.
    with redirect_stdout(io.StringIO()):
        _init_db(config)
    # Dispose again so the next caller sees a fresh engine bound to the
    # newly-created DB file rather than a stale handle from init_db.
    _dispose_engine()


def reset(config: Config) -> None:
    """Reset the DB baseline by reseeding from scratch."""
    seed(config)


def _sanitize_headers(headers: dict[str, str] | None) -> dict[str, str]:
    """Drop noisy values and replace auth tokens with placeholders."""
    if not headers:
        return {}

    sanitized: dict[str, str] = {}
    for key, value in headers.items():
        normalized = key.lower()
        if normalized in {'authorization'}:
            sanitized[normalized] = 'Bearer __TEST_TOKEN__'
            continue
        if normalized in {'x-workspace-id', 'content-type', 'content-disposition'}:
            sanitized[normalized] = value
    return sanitized


def create_stub(
    test_client: Any,
    stub: StubRequest,
) -> RecordedStub:
    """Perform one request through *test_client* and return a stub payload."""

    method_name = stub.method.lower()
    requester = getattr(test_client, method_name)
    request_kwargs: dict[str, Any] = {'params': stub.params, 'headers': stub.headers}
    if stub.body is not None:
        request_kwargs['json'] = stub.body
    if stub.multipart_files:
        files: list[tuple[str, tuple[str, bytes, str]]] = []
        for file_spec in stub.multipart_files:
            files.append(
                (
                    'files',
                    (
                        file_spec['filename'],
                        file_spec['content'].encode('utf-8'),
                        file_spec.get('content_type', 'application/octet-stream'),
                    ),
                )
            )
        request_kwargs['files'] = files

    response = requester(stub.endpoint, **request_kwargs)
    if response.status_code != stub.expected_status_code:
        raise ValueError(f'Expected status code {stub.expected_status_code} but got {response.status_code}')

    if stub.binary_response:
        response_body = base64.b64encode(response.content).decode('ascii')
    else:
        try:
            response_body = response.json()
        except ValueError:
            response_body = response.text

    if stub.multipart_files:
        stub.body = {
            'multipart_files': [
                {
                    'filename': file_spec['filename'],
                    'content_type': file_spec.get('content_type', 'application/octet-stream'),
                    'content': file_spec['content'],
                }
                for file_spec in stub.multipart_files
            ]
        }

    return RecordedStub(
        name=stub.name,
        endpoint=stub.endpoint,
        method=stub.method,
        params=stub.params,
        body=stub.body,
        headers=_sanitize_headers(stub.headers),
        response=StubResponse(
            body=response_body,
            status_code=response.status_code,
            headers=_sanitize_headers(dict(response.headers)),
        ),
    )


def _default_auth_headers(test_client: Any) -> dict[str, str]:
    token_response = test_client.post(
        '/auth/token',
        data={'username': 'bootstrap@example.com', 'password': 'password'},
    )
    token_response.raise_for_status()
    token = token_response.json()['access_token']

    workspaces_response = test_client.get(
        '/workspaces',
        headers={'Authorization': f'Bearer {token}'},
    )
    workspaces_response.raise_for_status()
    workspace_id = workspaces_response.json()[0]['id']

    return {
        'Authorization': f'Bearer {token}',
        'X-Workspace-Id': str(workspace_id),
    }


def write_stubs(output_dir: Path):
    """Generate and persist one predefined DB test stub JSON."""

    config = get_config()
    seed(config)

    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    client = TestClient(app)
    headers = _default_auth_headers(client)
    generated_payloads: dict[str, dict[str, Any]] = {}
    for stub in stubs(str(target_dir)):

        stub.headers = headers
        output_file = target_dir / f'{stub.name}.json'
        try:
            if stub.body_from_stub:
                source_payload = generated_payloads.get(stub.body_from_stub)
                if source_payload is None:
                    raise ValueError(f'Unknown body source stub "{stub.body_from_stub}" for "{stub.name}".')
                stub.body = source_payload['response']['body']

            recorded_stub = create_stub(client, stub)

            with output_file.open('w', encoding='utf-8') as handle:
                json.dump(recorded_stub.model_dump(), handle, indent=2, sort_keys=True)
                handle.write('\n')
            print('Stub written to', output_file)
        finally:
            if stub.reset_db:
                reset(config)
