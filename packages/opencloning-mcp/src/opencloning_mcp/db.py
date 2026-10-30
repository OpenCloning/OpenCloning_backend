"""Database model and setup. A single table: one row per cloning strategy.

There are no migrations: the table is created at startup if it does not exist.
"""

import os
from datetime import datetime, timezone

from sqlalchemy import JSON, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    # Stored without timezone, because SQLite does not keep it. All times in the table are UTC.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class StoredStrategy(Base):
    __tablename__ = 'mcp_strategy'

    # The strategy_id that the model passes to every tool (a random token)
    id: Mapped[str] = mapped_column(primary_key=True)
    # The OpenCloning CloningStrategy JSON
    strategy: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    # Updated every time a tool uses the strategy, inactive strategies are deleted
    last_used_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


engine = create_engine(os.environ.get('OPENCLONING_MCP_DB_URL', 'sqlite:///opencloning_mcp.sqlite'))


def init_db():
    Base.metadata.create_all(engine)
