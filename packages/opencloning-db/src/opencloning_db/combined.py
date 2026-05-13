"""Parent application that serves OpenCloning and opencloning-db under separate roots."""

from fastapi import FastAPI

from opencloning.main import create_app as create_cloning_app

from opencloning_db.api import create_app as create_db_app


app = FastAPI(
    title='OpenCloning Combined API',
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.mount('/cloning', create_cloning_app())
app.mount('/db', create_db_app())


@app.get('/')
async def root() -> dict[str, str]:
    return {
        'cloning': '/cloning',
        'cloning_docs': '/cloning/docs',
        'db': '/db',
        'db_docs': '/db/docs',
    }
