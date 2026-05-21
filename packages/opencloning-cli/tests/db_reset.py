"""Fast Postgres test database reset (truncate instead of drop/create)."""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from opencloning_db.models import Base


def ensure_schema(engine: Engine) -> None:
    """Create tables when the test database has no OpenCloning schema yet."""
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    expected = set(Base.metadata.tables.keys())
    if not expected.issubset(existing):
        Base.metadata.create_all(engine)


def reset_database(engine: Engine) -> None:
    """Clear all rows and reset sequences; much faster than drop_all/create_all per test."""
    ensure_schema(engine)
    table_names = list(Base.metadata.tables.keys())
    if not table_names:
        return
    quoted = ', '.join(f'"{name}"' for name in table_names)
    with engine.begin() as conn:
        conn.execute(text(f'TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE'))
