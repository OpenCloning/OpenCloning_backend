"""Parent application that serves OpenCloning and opencloning-db under separate roots."""

from fastapi import FastAPI
from starlette.types import ASGIApp

from opencloning.main import create_app as create_cloning_app

from opencloning_db.auth.middleware import AuthenticatedSubApp
from opencloning_db.api import create_app as create_db_app


def create_app(*, cloning_app: ASGIApp | None = None, db_app: ASGIApp | None = None) -> FastAPI:
    app = FastAPI(
        title='OpenCloning Combined API',
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    app.mount('/cloning', AuthenticatedSubApp(cloning_app or create_cloning_app()))
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
