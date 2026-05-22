import unittest
from unittest.mock import patch
import os
from pydantic import ValidationError
from opencloning_db.config import Config
import opencloning_db.config as app_config


common_args = {
    'database_url': 'postgresql+psycopg://dbuser:dbpassword@localhost:5432/opencloning_dev',
    'object_storage_endpoint_url': 'https://s3.amazonaws.com',
    'object_storage_access_key_id': 'test-access-key',
    'object_storage_secret_access_key': 'test-secret-key',
    'object_storage_bucket': 'opencloning-test',
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
                'OPENCLONING_OBJECT_STORAGE_ENDPOINT_URL': 'https://s3.amazonaws.com',
                'OPENCLONING_OBJECT_STORAGE_ACCESS_KEY_ID': 'test-access-key',
                'OPENCLONING_OBJECT_STORAGE_SECRET_ACCESS_KEY': 'test-secret-key',
                'OPENCLONING_OBJECT_STORAGE_BUCKET': 'opencloning-test',
                'OPENCLONING_JWT_SECRET': 'test-secret',
            },
            clear=True,
        ):
            app_config.set_config(None)
            cfg = app_config.get_config()
        app_config.set_config(previous_config)
        self.assertEqual(cfg.database_url, 'postgresql+psycopg://dbuser:dbpassword@localhost:5432/opencloning_dev')
        self.assertEqual(cfg.object_storage_endpoint_url, 'https://s3.amazonaws.com')
        self.assertEqual(cfg.object_storage_access_key_id, 'test-access-key')
        self.assertEqual(cfg.object_storage_secret_access_key, 'test-secret-key')
        self.assertEqual(cfg.object_storage_bucket, 'opencloning-test')
        self.assertEqual(cfg.object_storage_region, 'us-east-1')
        self.assertTrue(cfg.object_storage_force_path_style)
        self.assertEqual(cfg.sequence_objects_prefix, 'sequences/')
        self.assertEqual(cfg.sequencing_objects_prefix, 'sequencing-files/')
        self.assertEqual(cfg.jwt_secret, 'test-secret')

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
        self.assertIn('OPENCLONING_OBJECT_STORAGE_ENDPOINT_URL', message)
        self.assertIn('OPENCLONING_OBJECT_STORAGE_ACCESS_KEY_ID', message)
        self.assertIn('OPENCLONING_OBJECT_STORAGE_SECRET_ACCESS_KEY', message)
        self.assertIn('OPENCLONING_OBJECT_STORAGE_BUCKET', message)
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

    def test_object_storage_prefixes_must_not_be_empty(self):
        """Object storage prefixes must not be empty."""
        with self.assertRaises(ValidationError):
            Config(
                **(common_args | {'sequence_objects_prefix': ''}),
            )

        with self.assertRaises(ValidationError):
            Config(
                **(common_args | {'sequencing_objects_prefix': ''}),
            )
