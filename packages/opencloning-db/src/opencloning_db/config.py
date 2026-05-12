"""
Application configuration.

Values can be overridden by instantiating Config with different arguments,
or by loading from environment variables (e.g. via pydantic-settings).
"""

import os

from pydantic import BaseModel, Field


def parse_bool(value: str | bool) -> bool:
    return value in {'1', 'TRUE', 'true', 'True', True}


def _default_jwt_secret() -> str:
    """Development default; set OPENCLONING_JWT_SECRET in production."""
    return os.environ.get(
        'OPENCLONING_JWT_SECRET',
        'dev-only-use-openssl-rand-hex-32-in-production',
    )


DATABASE_DIR = os.getenv(
    'DATABASE_DIR', os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'dev_database')
)


class Config(BaseModel):
    """OpenCloning database configuration with sensible defaults."""

    database_url: str = Field(
        default=f'sqlite:///{DATABASE_DIR}/example.db',
        description='SQLAlchemy database URL (sqlite or postgresql)',
    )
    sequence_files_dir: str = Field(
        default=f'{DATABASE_DIR}/sequence_files',
        description='Directory for storing sequence GenBank files',
    )
    sequencing_files_dir: str = Field(
        default=f'{DATABASE_DIR}/sequencing_files',
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
    def database_path(self) -> str | None:
        """Path to DB file when using SQLite; None for non-file DBs."""
        if self.database_url.startswith('sqlite:///'):
            return self.database_url.removeprefix('sqlite:///')
        return None


config = Config()


def get_config() -> Config:
    return config


def set_config(new_config: Config) -> None:
    global config
    config = new_config
