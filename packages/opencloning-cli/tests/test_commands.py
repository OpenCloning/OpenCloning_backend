"""Smoke tests for the Typer command surface."""

from __future__ import annotations

from opencloning_cli.stubs import RecordedStub
import os
from pathlib import Path

from sqlalchemy.orm import Session
from typer.testing import CliRunner

import opencloning_db.db as db_module
from opencloning_db.models import User
from opencloning_cli.main import app

runner = CliRunner()


def _invoke(*args: str):
    # mix_stderr=False would be nicer on Click>=8.2 but Typer's CliRunner
    # surfaces both streams through result.output, which is enough for us.
    return runner.invoke(app, list(args))


def _count_users(config) -> int:
    with Session(db_module.get_engine(config)) as session:
        return session.query(User).count()


class TestHelpAndTree:
    def test_root_help(self):
        result = _invoke('--help')
        assert result.exit_code == 0
        assert 'db' in result.output

    def test_top_level_db_help(self):
        result = _invoke('db', '--help')
        assert result.exit_code == 0
        assert 'seed' in result.output
        assert 'reset' in result.output


class TestSeedCommand:
    def test_success_human_output(self, temp_workspace):
        _, config = temp_workspace

        result = _invoke('db', 'seed')

        assert result.exit_code == 0, result.output
        assert result.output.strip() == ''
        assert _count_users(config) > 0
        assert len(list(Path(config.sequence_files_dir).iterdir())) == 48
        assert len(list(Path(config.sequencing_files_dir).iterdir())) == 3


class TestResetCommand:
    def test_first_invocation_seeds(self, temp_workspace):
        _, config = temp_workspace

        result = _invoke('db', 'reset')

        assert result.exit_code == 0, result.output
        assert result.output.strip() == ''
        assert _count_users(config) > 0
        assert len(list(Path(config.sequence_files_dir).iterdir())) == 48

    def test_second_invocation_restores(self, temp_workspace):
        _, config = temp_workspace
        first = _invoke('db', 'reset')
        assert first.exit_code == 0

        expected_users = _count_users(config)
        with Session(db_module.get_engine(config)) as session:
            session.add(User(email='reset-extra@example.com'))
            session.commit()

        extra_file = Path(config.sequence_files_dir) / 'extra.txt'
        extra_file.write_text('stale-data', encoding='utf-8')

        second = _invoke('db', 'reset')
        assert second.exit_code == 0
        assert second.output.strip() == ''
        assert _count_users(config) == expected_users
        assert not extra_file.exists()


class TestStubCommand:
    def test_writes_single_stub_json(self, temp_workspace, monkeypatch):
        workspace, _ = temp_workspace
        monkeypatch.chdir(workspace)
        result = _invoke('db', 'stubs')

        assert result.exit_code == 0, result.output
        out_dir = workspace / 'stubs' / 'db'
        files = sorted(out_dir.glob('*.json'))
        stub_files_path = os.path.join(os.path.dirname(__file__), '..', 'src', 'opencloning_cli', 'stubs.py')
        with open(stub_files_path, 'r') as f:
            stub_files = f.read()
            yield_count = stub_files.count('yield')
        assert len(files) == yield_count

        for file in files:
            with open(file, 'r') as f:
                RecordedStub.model_validate_json(f.read())
