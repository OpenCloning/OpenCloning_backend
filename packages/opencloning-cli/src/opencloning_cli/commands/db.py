"""``opencloning-cli db`` command group.

Nested layout::

    db
      test
        seed
        reset
        snapshot
          create
          restore

Each command delegates directly to :mod:`lifecycle`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer

from opencloning_db.config import get_config

from .. import lifecycle

db_app = typer.Typer(no_args_is_help=True, help='Database management commands.')
db_test_app = typer.Typer(
    no_args_is_help=True,
    help=(
        'Commands for local/CI test runs that need a deterministic DB state. '
        'Typical flow: run `seed` once, run `snapshot create` once, then run '
        '`reset` between Cypress/E2E tests to restore the seeded baseline quickly.'
    ),
)
snapshot_app = typer.Typer(no_args_is_help=True, help='Manage the test-DB snapshot.')

db_app.add_typer(db_test_app, name='test')
db_test_app.add_typer(snapshot_app, name='snapshot')


SnapshotDirOption = Annotated[
    Optional[Path],
    typer.Option(
        '--snapshot-dir',
        help='Override the snapshot directory (default: <db parent>/snapshot).',
    ),
]

StubOutputDirOption = Annotated[
    Path,
    typer.Option(
        '--output-dir',
        help='Override generated stubs directory (default: ./stubs/db).',
    ),
]


@db_test_app.command('seed')
def seed_command() -> None:
    """Run ``init_db`` against the current test config."""
    config = get_config()
    lifecycle.seed(config)


@snapshot_app.command('create')
def snapshot_create_command(
    snapshot_dir: SnapshotDirOption = None,
) -> None:
    """Capture the current DB + file dirs as the golden snapshot."""
    config = get_config()
    target = lifecycle.resolve_snapshot_dir(config, snapshot_dir)
    lifecycle.snapshot_create(config, target)


@snapshot_app.command('restore')
def snapshot_restore_command(
    snapshot_dir: SnapshotDirOption = None,
) -> None:
    """Restore DB + file dirs from the golden snapshot."""
    config = get_config()
    target = lifecycle.resolve_snapshot_dir(config, snapshot_dir)
    lifecycle.snapshot_restore(config, target)


@db_test_app.command('reset')
def reset_command(
    snapshot_dir: SnapshotDirOption = None,
) -> None:
    """Fast-path restore; reseed + re-snapshot when the snapshot is missing."""
    config = get_config()
    target = lifecycle.resolve_snapshot_dir(config, snapshot_dir)
    lifecycle.reset(config, target)


@db_app.command('stubs')
def stubs_command(
    output_dir: StubOutputDirOption = Path('stubs/db'),
) -> None:
    """Generate a single JSON stub for DB/frontend testing."""
    lifecycle.write_stubs(output_dir)


__all__ = ['db_app']
