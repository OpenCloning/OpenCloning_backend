"""Top-level Typer application for ``opencloning-cli``.

The entry point registered in ``pyproject.toml`` as ``opencloning-cli`` is
:data:`app`.
"""

from __future__ import annotations

import typer

from .commands.db import db_app


app = typer.Typer(
    no_args_is_help=True,
    help='Command-line tools for OpenCloning.',
)
app.add_typer(db_app, name='db')


if __name__ == '__main__':  # pragma: no cover
    app()
