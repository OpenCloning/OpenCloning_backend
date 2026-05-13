"""``opencloning-cli db`` command group.

Nested layout::

        db
            seed
            reset
            stubs

Each command delegates directly to :mod:`lifecycle`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from opencloning_db.config import get_config

from .. import lifecycle

db_app = typer.Typer(no_args_is_help=True, help='Database management commands.')

StubOutputDirOption = Annotated[
    Path,
    typer.Option(
        '--output-dir',
        help='Override generated stubs directory (default: ./stubs/db).',
    ),
]


@db_app.command('seed')
def seed_command() -> None:
    """Run ``init_db`` against the current config."""
    config = get_config()
    lifecycle.seed(config)


@db_app.command('reset')
def reset_command() -> None:
    """Reset the DB baseline by reseeding from scratch."""
    config = get_config()
    lifecycle.reset(config)


@db_app.command('stubs')
def stubs_command(
    output_dir: StubOutputDirOption = Path('stubs/db'),
) -> None:
    """Generate stubs for DB/frontend testing."""
    lifecycle.write_stubs(output_dir)


__all__ = ['db_app']
