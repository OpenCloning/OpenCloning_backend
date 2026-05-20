"""FastAPI dependencies: database session and current user."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from sqlalchemy.orm import Session

from opencloning_db.auth.security import decode_access_token
from opencloning_db.config import Config, get_config
from opencloning_db.db import get_engine
from opencloning_db.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl='auth/token')


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


def resolve_user_from_token(token: str, session: Session, config: Config) -> User:
    exc = credentials_exception()
    try:
        payload = decode_access_token(token, config)
        sub = payload.get('sub')
        if sub is None:
            raise exc
        user_id = int(sub)
    except (InvalidTokenError, ValueError, TypeError):
        raise exc

    user = session.get(User, user_id)
    if user is None:
        raise exc
    return user


def get_db(config: Annotated[Config, Depends(get_config)]):
    session = Session(get_engine(config))
    try:
        yield session
    finally:
        session.close()


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: Annotated[Session, Depends(get_db)],
    config: Annotated[Config, Depends(get_config)],
) -> User:
    return resolve_user_from_token(token, session, config)
