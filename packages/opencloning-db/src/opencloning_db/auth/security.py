"""Password hashing (pwdlib) and JWT access tokens (PyJWT)."""

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from pwdlib import PasswordHash

from opencloning_db.config import Config

password_hasher = PasswordHash.recommended()


def get_password_hash(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_hasher.verify(plain_password, hashed_password)


def create_access_token(data: dict[str, Any], config: Config, expires_delta: timedelta) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({'exp': expire})
    encoded_jwt = jwt.encode(
        to_encode,
        config.jwt_secret,
        algorithm=config.jwt_algorithm,
    )
    return encoded_jwt


def decode_access_token(token: str, config: Config) -> dict[str, Any]:
    return jwt.decode(
        token,
        config.jwt_secret,
        algorithms=[config.jwt_algorithm],
    )
