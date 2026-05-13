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
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail='Could not validate credentials',
        headers={'WWW-Authenticate': 'Bearer'},
    )
    try:
        payload = decode_access_token(token, config)
        sub = payload.get('sub')
        if sub is None:
            raise credentials_exception
        user_id = int(sub)
    except (InvalidTokenError, ValueError, TypeError):
        raise credentials_exception
    user = session.get(User, user_id)
    if user is None:
        raise credentials_exception
    return user
