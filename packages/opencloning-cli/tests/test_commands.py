"""Smoke tests for the Typer command surface."""

from __future__ import annotations

from opencloning_cli.stubs import RecordedStub
import os
from pathlib import Path
import tempfile

from typer.testing import CliRunner

import opencloning_db.db as db_module
from opencloning_db.config import Config, get_config, set_config
from opencloning_cli.main import app

runner = CliRunner()


def _invoke(*args: str):
    # mix_stderr=False would be nicer on Click>=8.2 but Typer's CliRunner
    # surfaces both streams through result.output, which is enough for us.
    return runner.invoke(app, list(args))


class TestHelpAndTree:
    def test_root_help(self):
        result = _invoke('--help')
        assert result.exit_code == 0
        assert 'db' in result.output

    def test_snapshot_help(self):
        result = _invoke('db', 'snapshot', '--help')
        assert result.exit_code == 0
        assert 'create' in result.output
        assert 'restore' in result.output

    def test_top_level_db_help(self):
        result = _invoke('db', '--help')
        assert result.exit_code == 0
        assert 'seed' in result.output
        assert 'reset' in result.output
        assert 'snapshot' in result.output


class TestSeedCommand:
    def test_success_human_output(self, temp_workspace):
        _, config = temp_workspace

        result = _invoke('db', 'seed')

        assert result.exit_code == 0, result.output
        assert result.output.strip() == ''
        assert Path(config.database_path).exists()


class TestSnapshotCommands:
    def test_create_and_restore(self, temp_workspace):
        _, _ = temp_workspace

        assert _invoke('db', 'seed').exit_code == 0
        create = _invoke('db', 'snapshot', 'create')
        assert create.exit_code == 0, create.output
        snapshot_dir = Path(temp_workspace[1].database_path).parent / 'snapshot'
        assert (snapshot_dir / 'db' / Path(temp_workspace[1].database_path).name).exists()

        restore = _invoke('db', 'snapshot', 'restore')
        assert restore.exit_code == 0, restore.output

    def test_restore_missing_snapshot_exit_code(self, temp_workspace):
        result = _invoke('db', 'snapshot', 'restore')

        assert result.exit_code != 0

    def test_custom_snapshot_dir(self, temp_workspace, tmp_path):
        _, _ = temp_workspace
        assert _invoke('db', 'seed').exit_code == 0

        custom = tmp_path / 'custom-snapshot'
        result = _invoke('db', 'snapshot', 'create', '--snapshot-dir', str(custom))

        assert result.exit_code == 0
        assert (custom / 'db' / Path(temp_workspace[1].database_path).name).exists()


class TestResetCommand:
    def test_first_invocation_seeds(self, temp_workspace):
        _, config = temp_workspace

        result = _invoke('db', 'reset')

        assert result.exit_code == 0, result.output
        assert result.output.strip() == ''
        assert Path(config.database_path).exists()

    def test_second_invocation_restores(self, temp_workspace):
        first = _invoke('db', 'reset')
        assert first.exit_code == 0

        second = _invoke('db', 'reset')
        assert second.exit_code == 0
        assert second.output.strip() == ''

    def test_non_file_backend_reseeds_without_snapshot(self):
        default_config = get_config()
        default_engine = db_module._engine
        default_bound_url = db_module._bound_database_url
        db_module._engine = None
        db_module._bound_database_url = None

        with tempfile.TemporaryDirectory(prefix='opencloning-cli-non-file-') as tmp:
            workspace = Path(tmp)
            config = Config(
                database_url=f'sqlite+pysqlite:////{workspace / "test.db"}',
                jwt_secret='test-jwt-secret-not-for-production',
                sequence_files_dir=str(workspace / 'sequence_files'),
                sequencing_files_dir=str(workspace / 'sequencing_files'),
            )
            set_config(config)
            try:
                first = _invoke('db', 'reset')
                assert first.exit_code == 0, first.output

                extra_file = Path(config.sequence_files_dir) / 'extra.txt'
                extra_file.write_text('stale-data', encoding='utf-8')

                second = _invoke('db', 'reset')
                assert second.exit_code == 0, second.output
                assert not extra_file.exists()
            finally:
                if db_module._engine is not None:
                    db_module._engine.dispose()
                db_module._engine = default_engine
                db_module._bound_database_url = default_bound_url
                set_config(default_config)


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
