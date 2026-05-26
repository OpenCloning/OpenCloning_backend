"""Tests for opencloning_db.migrations helpers."""

from sqlalchemy import text
from sqlalchemy.orm import Session

from opencloning_db.init_db import load_seed_data
from opencloning_db.models import Base, User
from opencloning_db.migrations import truncate_application_tables


def test_truncate_application_tables_preserves_alembic_version(postgres_test_engine):
    """TRUNCATE must not target alembic_version (not in ORM metadata)."""
    assert 'alembic_version' not in Base.metadata.tables

    load_seed_data(postgres_test_engine)

    with postgres_test_engine.connect() as conn:
        version_before = conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one()

    with Session(postgres_test_engine) as session:
        assert session.query(User).count() > 0

    truncate_application_tables(postgres_test_engine)

    with postgres_test_engine.connect() as conn:
        version_after = conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
    assert version_after == version_before

    with Session(postgres_test_engine) as session:
        assert session.query(User).count() == 0
