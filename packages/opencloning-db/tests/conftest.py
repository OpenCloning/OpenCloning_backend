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
from sqlalchemy.engine import Engine
import pytest

import opencloning_db.auth.rate_limit as login_rate_limit
from opencloning_db.auth.rate_limit import LoginRateLimitConfig, reset_login_rate_limiter
from opencloning_db.migrations import reset_database

_JWT_SECRET = 'test-jwt-secret-not-for-production'
_TEST_DATABASE_URL_WRITE = os.environ.get(
    'OPENCLONING_TEST_DATABASE_URL',
    'postgresql+psycopg://dbuser:dbpassword@localhost:5432/opencloning_test',
)
_TEST_DATABASE_URL_READONLY = os.environ.get(
    'OPENCLONING_TEST_DATABASE_URL_READONLY',
    'postgresql+psycopg://dbuser:dbpassword@localhost:5432/opencloning_test_readonly',
)
_TEST_BUCKET = 'opencloning-test'
_TEST_REGION = 'us-east-1'
_TEST_ENDPOINT_URL = 'https://s3.amazonaws.com'


@pytest.fixture(autouse=True)
def _disable_login_rate_limit_for_tests(monkeypatch):
    reset_login_rate_limiter()
    monkeypatch.setattr(
        login_rate_limit,
        'LOGIN_RATE_LIMIT',
        LoginRateLimitConfig(enabled=False),
    )
    yield
    reset_login_rate_limiter()


def _build_postgres_test_config(default_config: Config | None, database_url: str) -> Generator[Config, None, None]:
    """Postgres test config backed by a Moto S3 bucket."""
    with mock_aws():
        boto3.client(
            's3',
            region_name=_TEST_REGION,
            aws_access_key_id='test-access-key',
            aws_secret_access_key='test-secret-key',
        ).create_bucket(Bucket=_TEST_BUCKET)
        test_config = Config(
            database_url=database_url,
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
def postgres_test_config_write() -> Generator[Config, None, None]:
    """Function-scoped config for mutating tests."""
    yield from _build_postgres_test_config(_peek_config(), _TEST_DATABASE_URL_WRITE)


@pytest.fixture(scope='module')
def postgres_test_config_readonly() -> Generator[Config, None, None]:
    """Module-scoped config for readonly_db-marked tests."""
    yield from _build_postgres_test_config(_peek_config(), _TEST_DATABASE_URL_READONLY)


@pytest.fixture
def postgres_test_engine_write(postgres_test_config_write: Config) -> Generator[Engine, None, None]:
    """Fresh schema bound to the shared Postgres test database."""
    engine = db_module.get_engine(postgres_test_config_write)
    reset_database(engine)
    yield engine


@pytest.fixture(scope='module')
def postgres_test_engine_readonly(postgres_test_config_readonly: Config) -> Generator[Engine, None, None]:
    """Single DB reset for readonly_db-marked tests in one module."""
    engine = db_module.get_engine(postgres_test_config_readonly)
    reset_database(engine)
    yield engine


def _engine_client_config(
    postgres_test_config: Config,
    postgres_test_engine: Engine,
) -> Generator[tuple[Engine, TestClient, Config], None, None]:
    """Shared TestClient/get_db wiring used by write and readonly chains."""

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


@pytest.fixture
def engine_client_config_write(
    postgres_test_config_write: Config,
    postgres_test_engine_write: Engine,
) -> Generator[tuple[Engine, TestClient, Config], None, None]:
    """Write DB (function scope) for mutating tests."""
    yield from _engine_client_config(postgres_test_config_write, postgres_test_engine_write)


@pytest.fixture(scope='module')
def engine_client_config_readonly(
    postgres_test_config_readonly: Config,
    postgres_test_engine_readonly: Engine,
) -> Generator[tuple[Engine, TestClient, Config], None, None]:
    """Readonly DB (module scope) shared by readonly_db-marked tests."""
    yield from _engine_client_config(postgres_test_config_readonly, postgres_test_engine_readonly)


@pytest.fixture
def postgres_test_config(postgres_test_config_write: Config) -> Generator[Config, None, None]:
    """Backward-compatible alias to write config."""
    yield postgres_test_config_write


@pytest.fixture
def postgres_test_engine(postgres_test_engine_write: Engine) -> Generator[Engine, None, None]:
    """Backward-compatible alias to write engine."""
    yield postgres_test_engine_write


@pytest.fixture
def engine_client_config(
    engine_client_config_write: tuple[Engine, TestClient, Config],
) -> Generator[tuple[Engine, TestClient, Config], None, None]:
    """Backward-compatible alias to write client stack.

    Also use via ``@pytest.mark.usefixtures("engine_client_config")`` when tests
    only need ``get_config()`` paths (e.g. model tests with their own engine).
    """
    yield engine_client_config_write
