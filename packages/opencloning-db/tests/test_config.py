import unittest
from unittest.mock import patch
import os
from pydantic import ValidationError
from opencloning_db.config import Config
import opencloning_db.config as app_config


common_args = {
    'database_url': 'postgresql+psycopg://dbuser:dbpassword@localhost:5432/opencloning_dev',
    'jwt_secret': 'test-secret',
}


class TestConfig(unittest.TestCase):
    """Tests for Config helpers."""

    def test_get_config_loads_required_values_from_env(self):
        """Runtime config is loaded lazily from the required env vars."""
        previous_config = app_config.config
        with patch.dict(
            os.environ,
            {
                'OPENCLONING_DB_URL': 'postgresql+psycopg://dbuser:dbpassword@localhost:5432/opencloning_dev',
                'OPENCLONING_JWT_SECRET': 'test-secret',
                'OPENCLONING_REGISTRATION_WHITELIST_ENABLED': 'true',
            },
            clear=True,
        ):
            app_config.set_config(None)
            cfg = app_config.get_config()
        app_config.set_config(previous_config)
        self.assertEqual(cfg.database_url, 'postgresql+psycopg://dbuser:dbpassword@localhost:5432/opencloning_dev')
        self.assertEqual(cfg.jwt_secret, 'test-secret')
        self.assertTrue(cfg.registration_whitelist_enabled)

    def test_get_config_requires_runtime_env_vars(self):
        """Missing env vars produce one actionable runtime error."""
        previous_config = app_config.config
        with patch.dict(os.environ, {}, clear=True):
            app_config.set_config(None)
            with self.assertRaises(RuntimeError) as exc_info:
                app_config.get_config()
        app_config.set_config(previous_config)

        message = str(exc_info.exception)
        self.assertIn('OPENCLONING_DB_URL', message)
        self.assertIn('OPENCLONING_JWT_SECRET', message)
        self.assertIn('.env.dev', message)

    def test_database_url_rejects_sqlite(self):
        """SQLite URLs are no longer accepted."""
        with self.assertRaises(ValidationError):
            Config(
                **(common_args | {'database_url': 'sqlite:///tmp/test.db'}),
            )

    def test_database_url_rejects_default_postgresql_driver(self):
        """Bare postgresql:// selects psycopg2 in SQLAlchemy; this package depends on psycopg3."""
        with self.assertRaises(ValidationError) as exc_info:
            Config(
                **(common_args | {'database_url': 'postgresql://dbuser:dbpassword@localhost:5432/opencloning_dev'}),
            )
        self.assertIn('postgresql+psycopg', str(exc_info.exception))

    def test_registration_whitelist_enabled_defaults_false(self):
        cfg = Config(**common_args)
        self.assertFalse(cfg.registration_whitelist_enabled)
