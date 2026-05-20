import os
from typing import Generator

import boto3
from moto import mock_aws
from sqlalchemy.orm import Session

from opencloning_db.config import Config, _peek_config
import opencloning_db.db as db_module
from fastapi.testclient import TestClient
from opencloning_db.api import app, fastapi_app
from opencloning_db.deps import get_db
from opencloning_db.models import Base
from sqlalchemy.engine import Engine
import pytest

_JWT_SECRET = 'test-jwt-secret-not-for-production'
_TEST_DATABASE_URL = os.environ.get(
    'OPENCLONING_TEST_DATABASE_URL',
    'postgresql+psycopg://postgres:postgres@localhost:5432/opencloning_test',
)
_TEST_BUCKET = 'opencloning-test'
_TEST_REGION = 'us-east-1'
_TEST_ENDPOINT_URL = 'https://s3.amazonaws.com'


@pytest.fixture
def postgres_test_config() -> Generator[Config, None, None]:
    """Postgres test config backed by a Moto S3 bucket."""
    default_config = _peek_config()
    with mock_aws():
        boto3.client(
            's3',
            region_name=_TEST_REGION,
            aws_access_key_id='test-access-key',
            aws_secret_access_key='test-secret-key',
        ).create_bucket(Bucket=_TEST_BUCKET)
        test_config = Config(
            database_url=_TEST_DATABASE_URL,
            object_storage_endpoint_url=_TEST_ENDPOINT_URL,
            object_storage_access_key_id='test-access-key',
            object_storage_secret_access_key='test-secret-key',
            object_storage_bucket=_TEST_BUCKET,
            object_storage_region=_TEST_REGION,
            object_storage_force_path_style=True,
            sequence_objects_prefix='sequences/',
            sequencing_objects_prefix='sequencing-files/',
            jwt_secret=_JWT_SECRET,
        )
        db_module.reset_runtime_state(test_config)
        yield test_config
    db_module.reset_runtime_state(default_config)


@pytest.fixture
def postgres_test_engine(postgres_test_config: Config) -> Generator[Engine, None, None]:
    """Fresh schema bound to the shared Postgres test database."""
    engine = db_module.get_engine(postgres_test_config)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine


@pytest.fixture
def engine_client_config(
    postgres_test_config: Config,
    postgres_test_engine: Engine,
) -> Generator[tuple[Engine, TestClient, Config], None, None]:
    """Temp file dirs plus a reset Postgres test DB, ``get_db`` override, and ``TestClient``.

    Also use via ``@pytest.mark.usefixtures("engine_client_config")`` when tests
    only need ``get_config()`` paths (e.g. model tests with their own engine).
    """

    def override_get_db():
        session = Session(postgres_test_engine)
        try:
            yield session
        finally:
            session.close()

    fastapi_app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield postgres_test_engine, client, postgres_test_config
    fastapi_app.dependency_overrides.pop(get_db, None)
