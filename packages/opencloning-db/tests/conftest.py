import os
from typing import Generator
from sqlalchemy.orm import Session

from opencloning_db.config import Config, _peek_config, set_config
import opencloning_db.db as db_module
from fastapi.testclient import TestClient
from opencloning_db.api import app
from opencloning_db.deps import get_db
from opencloning_db.models import Base
from sqlalchemy.engine import Engine
import tempfile
import pytest

_JWT_SECRET = 'test-jwt-secret-not-for-production'
_TEST_DATABASE_URL = os.environ.get(
    'OPENCLONING_TEST_DATABASE_URL',
    'postgresql+psycopg://postgres:postgres@localhost:5432/opencloning_test',
)


def _reset_engine_cache() -> None:
    if db_module._engine is not None:
        db_module._engine.dispose()
    db_module._engine = None
    db_module._bound_database_url = None


def _restore_runtime_state(default_config: Config | None, default_engine, default_bound_url: str | None) -> None:
    _reset_engine_cache()
    db_module._engine = default_engine
    db_module._bound_database_url = default_bound_url
    set_config(default_config)


@pytest.fixture
def postgres_test_config() -> Generator[Config, None, None]:
    """Postgres test config with isolated sequence and sequencing directories."""
    default_config = _peek_config()
    default_engine = db_module._engine
    default_bound_url = db_module._bound_database_url
    with tempfile.TemporaryDirectory() as tmp_dir_sequences:
        with tempfile.TemporaryDirectory() as tmp_dir_sequencing:
            test_config = Config(
                database_url=_TEST_DATABASE_URL,
                jwt_secret=_JWT_SECRET,
                sequence_files_dir=tmp_dir_sequences,
                sequencing_files_dir=tmp_dir_sequencing,
            )
            _reset_engine_cache()
            set_config(test_config)
            yield test_config
    _restore_runtime_state(default_config, default_engine, default_bound_url)


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

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield postgres_test_engine, client, postgres_test_config
    app.dependency_overrides.pop(get_db, None)
