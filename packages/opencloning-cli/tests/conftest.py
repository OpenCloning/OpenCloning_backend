"""Shared fixtures for opencloning-cli smoke tests."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Generator

import boto3
import pytest
from moto import mock_aws

from opencloning_db.config import Config, _peek_config
import opencloning_db.db as db_module

_TEST_DATABASE_URL = os.environ.get(
    'OPENCLONING_TEST_DATABASE_URL',
    'postgresql+psycopg://dbuser:dbpassword@localhost:5432/opencloning_test',
)
_TEST_BUCKET = 'opencloning-cli-test'
_TEST_REGION = 'us-east-1'
_TEST_ENDPOINT_URL = 'https://s3.amazonaws.com'


@pytest.fixture
def temp_workspace() -> Generator[tuple[Path, Config], None, None]:
    """Yield ``(workspace_dir, config)`` pointing at a temp test workspace."""
    default_config = _peek_config()

    with mock_aws():
        boto3.client(
            's3',
            region_name=_TEST_REGION,
            aws_access_key_id='test-access-key',
            aws_secret_access_key='test-secret-key',
        ).create_bucket(Bucket=_TEST_BUCKET)
        config = Config(
            database_url=_TEST_DATABASE_URL,
            object_storage_endpoint_url=_TEST_ENDPOINT_URL,
            object_storage_access_key_id='test-access-key',
            object_storage_secret_access_key='test-secret-key',
            object_storage_bucket=_TEST_BUCKET,
            object_storage_region=_TEST_REGION,
            object_storage_force_path_style=True,
            sequence_objects_prefix='sequences/',
            sequencing_objects_prefix='sequencing-files/',
            jwt_secret='test-jwt-secret-not-for-production',
        )
        db_module.reset_runtime_state(config)
        with tempfile.TemporaryDirectory(prefix='opencloning-cli-test-') as tmp:
            workspace = Path(tmp)
            yield workspace, config
    db_module.reset_runtime_state(default_config)
