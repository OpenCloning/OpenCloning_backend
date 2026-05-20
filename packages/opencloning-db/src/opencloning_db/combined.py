"""Parent application that serves OpenCloning and opencloning-db under separate roots."""

from fastapi import FastAPI
from sqlalchemy.orm import Session
from starlette.datastructures import Headers
from starlette.types import ASGIApp

from opencloning.main import create_app as create_cloning_app

from opencloning_db.auth.middleware import AuthenticatedSubApp, RequestVerifier
from opencloning_db.api import create_app as create_db_app
from opencloning_db.config import get_config
from opencloning_db.db import get_engine
from opencloning_db.deps import parse_bearer_token, resolve_user_from_token


def verify_local_bearer_request(headers: Headers) -> None:
    config = get_config()
    session = Session(get_engine(config))
    try:
        token = parse_bearer_token(headers.get('authorization'))
        resolve_user_from_token(token, session, config)
    finally:
        session.close()


def create_app(
    *,
    cloning_app: ASGIApp | None = None,
    db_app: ASGIApp | None = None,
    cloning_verifier: RequestVerifier | None = None,
) -> FastAPI:
    app = FastAPI(
        title='OpenCloning Combined API',
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    app.mount(
        '/cloning',
        AuthenticatedSubApp(cloning_app or create_cloning_app(), cloning_verifier or verify_local_bearer_request),
    )
    app.mount('/db', db_app or create_db_app())

    @app.get('/')
    async def root() -> dict[str, str]:
        return {
            'cloning': '/cloning',
            'cloning_docs': '/cloning/docs',
            'db': '/db',
            'db_docs': '/db/docs',
        }

    return app


app = create_app()
