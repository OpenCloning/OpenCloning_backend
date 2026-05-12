"""Shared fixtures for opencloning-cli smoke tests."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Generator

import pytest

import opencloning_db.db as db_module
from opencloning_db.config import Config, get_config, set_config


@pytest.fixture
def temp_workspace() -> Generator[tuple[Path, Config], None, None]:
    """Yield ``(workspace_dir, config)`` pointing at a temp test workspace."""
    default_config = get_config()
    default_engine = db_module._engine
    default_bound_url = db_module._bound_database_url
    db_module._engine = None
    db_module._bound_database_url = None

    with tempfile.TemporaryDirectory(prefix='opencloning-cli-test-') as tmp:
        workspace = Path(tmp)
        config = Config(
            database_url=f'sqlite:///{workspace}/test.db',
            jwt_secret='test-jwt-secret-not-for-production',
            sequence_files_dir=str(workspace / 'sequence_files'),
            sequencing_files_dir=str(workspace / 'sequencing_files'),
        )
        set_config(config)
        try:
            yield workspace, config
        finally:
            if db_module._engine is not None:
                db_module._engine.dispose()
            db_module._engine = default_engine
            db_module._bound_database_url = default_bound_url
            set_config(default_config)
