"""Alembic helpers for schema management and test database resets."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text
from sqlalchemy.engine import Engine

from opencloning_db.models import Base


def _alembic_root() -> Path:
    """Directory containing ``alembic.ini`` (package root in dev, site-packages when bundled)."""
    here = Path(__file__).resolve()
    for root in (here.parents[2], here.parents[1]):
        if (root / 'alembic.ini').is_file():
            return root
    raise RuntimeError('Could not locate alembic.ini next to opencloning-db package')


def _database_url(database_url: str | None = None) -> str:
    url = database_url or os.environ.get('OPENCLONING_DB_URL')
    if not url:
        raise RuntimeError('OPENCLONING_DB_URL is required for Alembic. For local development load .env.dev')
    return url


def _alembic_config(database_url: str) -> AlembicConfig:
    cfg = AlembicConfig(str(_alembic_root() / 'alembic.ini'))
    cfg.set_main_option('sqlalchemy.url', database_url)
    return cfg


def upgrade_head(database_url: str | None = None) -> None:
    """Apply all pending Alembic revisions (creates schema from empty DB at head)."""
    for logger_name in ('alembic', 'alembic.runtime.migration'):
        logging.getLogger(logger_name).setLevel(logging.WARNING)
    command.upgrade(_alembic_config(_database_url(database_url)), 'head')


def recreate_public_schema(engine: Engine) -> None:
    """Drop and recreate the public schema (destructive)."""
    with engine.begin() as conn:
        conn.execute(text('DROP SCHEMA public CASCADE'))
        conn.execute(text('CREATE SCHEMA public'))
        conn.execute(text('GRANT ALL ON SCHEMA public TO public'))
        conn.execute(text('GRANT ALL ON SCHEMA public TO CURRENT_USER'))


def truncate_application_tables(engine: Engine) -> None:
    """Clear all rows from ORM tables; leaves ``alembic_version`` untouched."""
    table_names = list(Base.metadata.tables.keys())
    if not table_names:
        return
    quoted = ', '.join(f'"{name}"' for name in table_names)
    with engine.begin() as conn:
        conn.execute(text(f'TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE'))


def ensure_schema(engine: Engine) -> None:
    """Ensure the database schema is at Alembic head."""
    upgrade_head(engine.url.render_as_string(hide_password=False))


def reset_database(engine: Engine) -> None:
    """Ensure schema at head and truncate all application tables."""
    ensure_schema(engine)
    truncate_application_tables(engine)
