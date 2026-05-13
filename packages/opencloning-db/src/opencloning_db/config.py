"""
Application configuration.

Runtime config is loaded lazily from environment variables via ``get_config()``.
Tests and other callers can still instantiate ``Config`` directly.
"""

import os

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.engine import make_url

_ENV_TO_FIELD = {
    'OPENCLONING_DATABASE_URL': 'database_url',
    'OPENCLONING_SEQUENCE_FILES_DIR': 'sequence_files_dir',
    'OPENCLONING_SEQUENCING_FILES_DIR': 'sequencing_files_dir',
    'OPENCLONING_JWT_SECRET': 'jwt_secret',
}


def parse_bool(value: str | bool) -> bool:
    return value in {'1', 'TRUE', 'true', 'True', True}


def _load_config_from_env() -> 'Config':
    missing_vars = [env_name for env_name in _ENV_TO_FIELD if not os.environ.get(env_name)]
    if missing_vars:
        missing = ', '.join(missing_vars)
        raise RuntimeError(
            'Missing required OpenCloning environment variables: ' f'{missing}. For local development load .env.dev'
        )

    return Config(
        database_url=os.environ['OPENCLONING_DATABASE_URL'],
        sequence_files_dir=os.environ['OPENCLONING_SEQUENCE_FILES_DIR'],
        sequencing_files_dir=os.environ['OPENCLONING_SEQUENCING_FILES_DIR'],
        jwt_secret=os.environ['OPENCLONING_JWT_SECRET'],
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

    database_url: str = Field(
        description='SQLAlchemy PostgreSQL URL using the psycopg (v3) driver (postgresql+psycopg://...)',
    )
    sequence_files_dir: str = Field(
        description='Directory for storing sequence GenBank files',
    )
    sequencing_files_dir: str = Field(
        description='Directory for storing uploaded sequencing files (ab1, fasta, etc.)',
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
