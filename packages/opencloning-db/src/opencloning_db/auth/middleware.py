"""Authentication wrappers for mounted ASGI applications."""

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from opencloning_db.config import get_config
from opencloning_db.db import get_engine
from opencloning_db.deps import parse_bearer_token, resolve_user_from_token


class AuthenticatedSubApp:
    """Require bearer authentication before forwarding to a mounted sub-application."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http' or scope['method'] == 'OPTIONS':
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        config = get_config()
        session = Session(get_engine(config))
        try:
            token = parse_bearer_token(headers.get('authorization'))
            resolve_user_from_token(token, session, config)
        except HTTPException as exc:
            response = JSONResponse(
                {'detail': exc.detail},
                status_code=exc.status_code,
                headers=exc.headers,
            )
            await response(scope, receive, send)
            return
        finally:
            session.close()

        await self.app(scope, receive, send)
