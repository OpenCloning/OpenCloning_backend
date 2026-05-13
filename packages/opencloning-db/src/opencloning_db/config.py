"""
Application configuration.

Values can be overridden by instantiating Config with different arguments,
or by loading from environment variables (e.g. via pydantic-settings).
"""

import os

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.engine import make_url


def parse_bool(value: str | bool) -> bool:
    return value in {'1', 'TRUE', 'true', 'True', True}


def _default_jwt_secret() -> str:
    """Development default; set OPENCLONING_JWT_SECRET in production."""
    return os.environ.get(
        'OPENCLONING_JWT_SECRET',
        'dev-only-use-openssl-rand-hex-32-in-production',
    )


def _default_database_dir() -> str:
    return os.environ.get(
        'DATABASE_DIR',
        os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'dev_database'),
    )


def _default_database_url() -> str:
    return (
        os.environ.get('OPENCLONING_DATABASE_URL')
        or os.environ.get('DATABASE_URL')
        or 'postgresql+psycopg://postgres:postgres@localhost:5432/opencloning_dev'
    )


def _default_sequence_files_dir() -> str:
    return os.environ.get('OPENCLONING_SEQUENCE_FILES_DIR', f'{_default_database_dir()}/sequence_files')


def _default_sequencing_files_dir() -> str:
    return os.environ.get('OPENCLONING_SEQUENCING_FILES_DIR', f'{_default_database_dir()}/sequencing_files')


class Config(BaseModel):
    """OpenCloning database configuration with sensible defaults."""

    @field_validator('database_url')
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        if make_url(value).get_backend_name() != 'postgresql':
            raise ValueError('Only PostgreSQL database URLs are supported.')
        return value

    database_url: str = Field(
        default_factory=_default_database_url,
        description='SQLAlchemy PostgreSQL database URL',
    )
    sequence_files_dir: str = Field(
        default_factory=_default_sequence_files_dir,
        description='Directory for storing sequence GenBank files',
    )
    sequencing_files_dir: str = Field(
        default_factory=_default_sequencing_files_dir,
        description='Directory for storing uploaded sequencing files (ab1, fasta, etc.)',
    )
    jwt_secret: str = Field(
        default_factory=_default_jwt_secret,
        description='HS256 signing key for JWT access tokens; override OPENCLONING_JWT_SECRET in production',
    )
    jwt_algorithm: str = Field(default='HS256', description='JWT signing algorithm')
    access_token_expire_minutes: int = Field(
        default=60,
        ge=1,
        description='Access token lifetime in minutes',
    )

    @property
    def database_backend(self) -> str:
        return make_url(self.database_url).get_backend_name()


config = Config()


def get_config() -> Config:
    return config


def set_config(new_config: Config) -> None:
    global config
    config = new_config
