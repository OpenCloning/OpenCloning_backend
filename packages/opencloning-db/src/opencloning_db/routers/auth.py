"""Registration, OAuth2 token (login), and current user endpoints."""

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from opencloning_db.apimodels import RegisterBody, Token, UserPublic
from opencloning_db.auth.rate_limit import check_login_rate_limit
from opencloning_db.auth.invites import normalize_email, require_invited_email
from opencloning_db.auth.security import (
    create_access_token,
    get_password_hash,
    verify_password,
)
from opencloning_db.config import Config, get_config
from opencloning_db.deps import get_current_user, get_db
from opencloning_db.models import User, Workspace, WorkspaceMembership, WorkspaceRole

router = APIRouter(prefix='/auth', tags=['auth'])


@router.post('/register', response_model=Token)
def register(
    body: RegisterBody,
    session: Annotated[Session, Depends(get_db)],
    config: Annotated[Config, Depends(get_config)],
) -> Token:
    email = normalize_email(body.email)
    existing = session.scalar(select(User).where(User.email.ilike(f"%{email}%")))
    if existing is not None:
        raise HTTPException(status_code=400, detail='Email already registered')
    require_invited_email(email, config)
    user = User(
        email=email,
        display_name=body.display_name,
        password_hash=get_password_hash(body.password),
    )

    workspace = Workspace(name=f"{body.display_name}'s workspace")
    session.add(user)
    session.add(workspace)
    session.flush()
    session.add(
        WorkspaceMembership(
            user_id=user.id,
            workspace_id=workspace.id,
            role=WorkspaceRole.owner,
        )
    )
    session.commit()
    access_token_expires = timedelta(minutes=config.access_token_expire_minutes)
    access_token = create_access_token({'sub': str(user.id)}, config, access_token_expires)
    return Token(access_token=access_token, token_type='bearer')


@router.post('/token', response_model=Token)
def login_for_access_token(
    _rate_limit: Annotated[None, Depends(check_login_rate_limit)],
    session: Annotated[Session, Depends(get_db)],
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    config: Annotated[Config, Depends(get_config)],
) -> Token:
    """OAuth2-style login: `username` field carries the account email."""
    user = session.scalar(select(User).where(User.email.ilike(f"%{normalize_email(form_data.username)}%")))
    if user is None or user.password_hash is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Incorrect username or password',
            headers={'WWW-Authenticate': 'Bearer'},
        )
    if not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Incorrect username or password',
            headers={'WWW-Authenticate': 'Bearer'},
        )
    access_token_expires = timedelta(minutes=config.access_token_expire_minutes)
    access_token = create_access_token({'sub': str(user.id)}, config, access_token_expires)
    return Token(access_token=access_token, token_type='bearer')


@router.get('/me', response_model=UserPublic)
def read_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserPublic:
    return UserPublic(
        id=current_user.id,
        email=current_user.email,
        display_name=current_user.display_name,
        is_instance_admin=current_user.is_instance_admin,
    )
