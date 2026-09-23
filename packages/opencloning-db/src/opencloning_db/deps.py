"""FastAPI dependencies: database session and current user."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import InvalidTokenError
from sqlalchemy.orm import Session

from opencloning_db.auth.oidc import verify_oidc_bearer_token
from opencloning_db.auth.provisioning import resolve_oidc_user
from opencloning_db.config import Config, get_config
from opencloning_db.db import get_engine
from opencloning_db.models import User

bearer_scheme = HTTPBearer()


def credentials_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail='Could not validate credentials',
        headers={'WWW-Authenticate': 'Bearer'},
    )


def parse_bearer_token(authorization: str | None) -> str:
    if authorization is None:
        raise credentials_exception()

    scheme, _, token = authorization.partition(' ')
    if scheme.lower() != 'bearer' or not token:
        raise credentials_exception()
    return token


async def resolve_user_from_token(token: str, session: Session, config: Config) -> User:
    try:
        identity = await verify_oidc_bearer_token(token, config)
        return resolve_oidc_user(session, config, identity)
    except InvalidTokenError:
        raise credentials_exception()


def get_db(config: Annotated[Config, Depends(get_config)]):
    session = Session(get_engine(config))
    try:
        yield session
    finally:
        session.close()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    session: Annotated[Session, Depends(get_db)],
    config: Annotated[Config, Depends(get_config)],
) -> User:
    return await resolve_user_from_token(credentials.credentials, session, config)
