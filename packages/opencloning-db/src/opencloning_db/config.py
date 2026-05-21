"""
Application configuration.

Runtime config is loaded lazily from environment variables via ``get_config()``.
Tests and other callers can still instantiate ``Config`` directly.
"""

import os

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.engine import URL, make_url

_DB_ENV_VARS = (
    'OPENCLONING_DB_USER',
    'OPENCLONING_DB_PASSWORD',
    'OPENCLONING_DB_HOST',
    'OPENCLONING_DB_PORT',
    'OPENCLONING_DB_NAME',
)

_REQUIRED_ENV_VARS = (
    *_DB_ENV_VARS,
    'OPENCLONING_OBJECT_STORAGE_ENDPOINT_URL',
    'OPENCLONING_OBJECT_STORAGE_ACCESS_KEY_ID',
    'OPENCLONING_OBJECT_STORAGE_SECRET_ACCESS_KEY',
    'OPENCLONING_OBJECT_STORAGE_BUCKET',
    'OPENCLONING_JWT_SECRET',
)


def parse_bool(value: str | bool) -> bool:
    return value in {'1', 'TRUE', 'true', 'True', True}


def build_database_url(*, user: str, password: str, host: str, port: str | int, database: str) -> str:
    """Build a SQLAlchemy PostgreSQL URL using the psycopg (v3) driver."""
    return URL.create(
        drivername='postgresql+psycopg',
        username=user,
        password=password,
        host=host,
        port=int(port),
        database=database,
    ).render_as_string(hide_password=False)


def _load_config_from_env() -> 'Config':
    missing_vars = [env_name for env_name in _REQUIRED_ENV_VARS if not os.environ.get(env_name)]
    if missing_vars:
        missing = ', '.join(missing_vars)
        raise RuntimeError(
            'Missing required OpenCloning environment variables: ' f'{missing}. For local development load .env.dev'
        )

    return Config(
        database_url=build_database_url(
            user=os.environ['OPENCLONING_DB_USER'],
            password=os.environ['OPENCLONING_DB_PASSWORD'],
            host=os.environ['OPENCLONING_DB_HOST'],
            port=os.environ['OPENCLONING_DB_PORT'],
            database=os.environ['OPENCLONING_DB_NAME'],
        ),
        object_storage_endpoint_url=os.environ['OPENCLONING_OBJECT_STORAGE_ENDPOINT_URL'],
        object_storage_access_key_id=os.environ['OPENCLONING_OBJECT_STORAGE_ACCESS_KEY_ID'],
        object_storage_secret_access_key=os.environ['OPENCLONING_OBJECT_STORAGE_SECRET_ACCESS_KEY'],
        object_storage_bucket=os.environ['OPENCLONING_OBJECT_STORAGE_BUCKET'],
        object_storage_region=os.environ.get('OPENCLONING_OBJECT_STORAGE_REGION', 'us-east-1'),
        object_storage_force_path_style=parse_bool(os.environ.get('OPENCLONING_OBJECT_STORAGE_FORCE_PATH_STYLE', '1')),
        sequence_objects_prefix=os.environ.get('OPENCLONING_SEQUENCE_OBJECTS_PREFIX', 'sequences/'),
        sequencing_objects_prefix=os.environ.get('OPENCLONING_SEQUENCING_OBJECTS_PREFIX', 'sequencing-files/'),
        jwt_secret=os.environ['OPENCLONING_JWT_SECRET'],
        registration_invites_object_key=os.environ.get('OPENCLONING_REGISTRATION_INVITES_OBJECT_KEY', '').strip(),
    )


class Config(BaseModel):
    """OpenCloning database configuration."""

    @field_validator('database_url')
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        url = make_url(value)
        if url.get_backend_name() != 'postgresql':
            raise ValueError('Only PostgreSQL database URLs are supported.')
        if url.drivername != 'postgresql+psycopg':
            raise ValueError(
                'Only PostgreSQL database URLs using the psycopg driver are supported ' '(postgresql+psycopg://...).'
            )
        return value

    @field_validator('sequence_objects_prefix', 'sequencing_objects_prefix')
    @classmethod
    def _normalize_object_prefix(cls, value: str) -> str:
        normalized = value.strip('/')
        if not normalized:
            raise ValueError('Object storage prefixes must not be empty.')
        return f'{normalized}/'

    database_url: str = Field(
        description='SQLAlchemy PostgreSQL URL using the psycopg (v3) driver (postgresql+psycopg://...)',
    )
    object_storage_endpoint_url: str = Field(
        description='S3-compatible endpoint URL used for object storage operations',
        pattern=r'^https?://',
    )
    object_storage_access_key_id: str = Field(
        description='Access key ID for the configured S3-compatible object storage',
    )
    object_storage_secret_access_key: str = Field(
        description='Secret access key for the configured S3-compatible object storage',
    )
    object_storage_bucket: str = Field(
        description='Bucket name used for both sequence and sequencing-file objects',
    )
    object_storage_region: str = Field(
        default='us-east-1',
        description='Region name for the configured S3-compatible object storage',
    )
    object_storage_force_path_style: bool = Field(
        default=True,
        description='Whether to force path-style S3 addressing (typically required for local S3-compatible endpoints)',
    )
    sequence_objects_prefix: str = Field(
        default='sequences/',
        description='Object-key prefix for sequence GenBank files',
    )
    sequencing_objects_prefix: str = Field(
        default='sequencing-files/',
        description='Object-key prefix for uploaded sequencing files',
    )
    jwt_secret: str = Field(
        description='HS256 signing key for JWT access tokens',
    )
    jwt_algorithm: str = Field(default='HS256', description='JWT signing algorithm')
    access_token_expire_minutes: int = Field(
        default=60,
        ge=1,
        description='Access token lifetime in minutes',
    )
    registration_invites_object_key: str = Field(
        default='',
        description='S3 object key for signup allowlist (one email per line). Empty disables invite checks.',
    )


config: Config | None = None


def _peek_config() -> Config | None:
    return config


def get_config() -> Config:
    global config
    if config is None:
        config = _load_config_from_env()
    return config


def set_config(new_config: Config | None) -> None:
    global config
    config = new_config
