#!/usr/bin/env python3
"""Ensure that UnscopedSession is only used where bypassing workspace scoping is intended.

UnscopedSession sees and writes the data of all workspaces, so application code must not use it.
Only its definition may reference it. Tests (packages/<package>/tests/) are excluded by the pre-commit hook.
"""
import ast
import sys
from pathlib import Path

ALLOWED_FILES = {
    'packages/opencloning-db/src/opencloning_db/workspace_scope.py',  # definition
}


def uses_unscoped_session(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and any(alias.name == 'UnscopedSession' for alias in node.names):
            return True
        if isinstance(node, ast.Name) and node.id == 'UnscopedSession':
            return True
        if isinstance(node, ast.Attribute) and node.attr == 'UnscopedSession':
            return True
    return False


def check_file(file_path: Path) -> bool:
    """Check that UnscopedSession is not used in the file, unless it is allowed."""
    if file_path.as_posix() in ALLOWED_FILES:
        return True
    try:
        tree = ast.parse(file_path.read_text(encoding='utf-8'))
    except SyntaxError:
        print(f'Error: Could not parse {file_path}')
        return False
    if uses_unscoped_session(tree):
        print(f'Error: UnscopedSession used in {file_path}')
        print('UnscopedSession bypasses workspace scoping and is only allowed in: ' + ', '.join(sorted(ALLOWED_FILES)))
        return False
    return True


def main():
    files = sys.argv[1:]
    if not files:
        print('No files provided')
        sys.exit(1)

    failed = False
    for file_path in files:
        if not check_file(Path(file_path)):
            failed = True

    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
