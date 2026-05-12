"""
OpenCloning API - main FastAPI application.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi_pagination import add_pagination
import os

from opencloning_db.config import parse_bool
from opencloning_db.routers import (
    auth,
    lines,
    primers,
    sequence_samples,
    sequences,
    template_sequences,
    tags,
    test_tools,
    workspaces,
)

app = FastAPI(title='OpenCloning API')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

app.include_router(auth.router)
app.include_router(workspaces.router)
app.include_router(tags.router)
app.include_router(primers.router)
app.include_router(sequences.router)
app.include_router(template_sequences.router)
app.include_router(lines.router)
app.include_router(sequence_samples.router)
if parse_bool(os.getenv('OPENCLONING_TESTING', False)):
    app.include_router(test_tools.router)

# Register routes first so Page[...] endpoints get pagination_ctx.
add_pagination(app)
