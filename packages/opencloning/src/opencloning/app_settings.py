"""
This module contains the settings for the app that can be set via environment variables.
"""

import os
from pydantic import BaseModel


def parse_bool(value: str | bool) -> bool:
    return value in {'1', 'TRUE', 'true', 'True', True}


# API settings ===============================================
SERVE_FRONTEND = parse_bool(os.environ['SERVE_FRONTEND']) if 'SERVE_FRONTEND' in os.environ else False
BATCH_CLONING = parse_bool(os.environ['BATCH_CLONING']) if 'BATCH_CLONING' in os.environ else True
RECORD_STUBS = parse_bool(os.environ['RECORD_STUBS']) if 'RECORD_STUBS' in os.environ else False
ALLOWED_ORIGINS = ['http://localhost:3000', 'http://localhost:5173', 'http://localhost:3002']
if os.environ.get('ALLOWED_ORIGINS') is not None:
    # Remove trailing slash from each origin if ends with one
    ALLOWED_ORIGINS = [
        origin.rstrip('/') for origin in os.environ['ALLOWED_ORIGINS'].split(',') if origin.rstrip('/') != ''
    ]


# External services settings =================================
NCBI_API_KEY = os.environ.get('NCBI_API_KEY')
NCBI_MAX_SEQUENCE_LENGTH = (
    int(os.environ.get('NCBI_MAX_SEQUENCE_LENGTH'))
    if os.environ.get('NCBI_MAX_SEQUENCE_LENGTH') is not None
    else 500000
)
PLANNOTATE_URL = os.environ['PLANNOTATE_URL'] if 'PLANNOTATE_URL' in os.environ else None
PLANNOTATE_TIMEOUT = int(os.environ['PLANNOTATE_TIMEOUT']) if 'PLANNOTATE_TIMEOUT' in os.environ else 20
# Handle trailing slash:
if PLANNOTATE_URL is not None and not PLANNOTATE_URL.endswith('/'):
    PLANNOTATE_URL += '/'

PROXY_URL = os.environ.get('PROXY_URL')
PROXY_CERT_FILE = os.environ.get('PROXY_CERT_FILE')
ADDGENE_USERNAME = os.environ.get('ADDGENE_USERNAME')
ADDGENE_PASSWORD = os.environ.get('ADDGENE_PASSWORD')

# Allowed external URLs ===========================================
default_allowed_urls = [
    'https://www.addgene.org/',
    'https://media.addgene.org/',
    'https://seva-plasmids.com/',
    'https://api.ncbi.nlm.nih.gov/datasets/v2alpha/',
    'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/',
    'https://www.snapgene.com/local/fetch.php',
    'https://benchling.com/',
    'https://assets.opencloning.org/annotated-igem-distribution',
    'http://www.euroscarf.de/',
    'https://wekwikgene.wllsb.edu.cn',
    'http://bahlerweb.cs.ucl.ac.uk',
    'https://assets.opencloning.org/open-dna-collections',
    'https://goldenbraidpro.com/do/',
]

if os.environ.get('ALLOWED_EXTERNAL_URLS') is not None:
    ALLOWED_EXTERNAL_URLS = os.environ['ALLOWED_EXTERNAL_URLS'].split(',')
else:
    ALLOWED_EXTERNAL_URLS = default_allowed_urls


class Settings(BaseModel):
    SERVE_FRONTEND: bool
    BATCH_CLONING: bool
    RECORD_STUBS: bool
    NCBI_API_KEY: str | None
    NCBI_MAX_SEQUENCE_LENGTH: int
    ALLOWED_ORIGINS: list[str]
    PLANNOTATE_URL: str | None
    PLANNOTATE_TIMEOUT: int
    PROXY_URL: str | None
    # Must be a full path to the proxy certificate file
    PROXY_CERT_FILE: str | None
    ADDGENE_USERNAME: str | None
    ADDGENE_PASSWORD: str | None
    # Allowed external URLs
    ALLOWED_EXTERNAL_URLS: list[str]


settings = Settings(
    SERVE_FRONTEND=SERVE_FRONTEND,
    BATCH_CLONING=BATCH_CLONING,
    RECORD_STUBS=RECORD_STUBS,
    NCBI_API_KEY=NCBI_API_KEY,
    NCBI_MAX_SEQUENCE_LENGTH=NCBI_MAX_SEQUENCE_LENGTH,
    ALLOWED_ORIGINS=ALLOWED_ORIGINS,
    PLANNOTATE_URL=PLANNOTATE_URL,
    PLANNOTATE_TIMEOUT=PLANNOTATE_TIMEOUT,
    PROXY_URL=PROXY_URL,
    PROXY_CERT_FILE=PROXY_CERT_FILE,
    ADDGENE_USERNAME=ADDGENE_USERNAME,
    ADDGENE_PASSWORD=ADDGENE_PASSWORD,
    ALLOWED_EXTERNAL_URLS=ALLOWED_EXTERNAL_URLS,
)


class FrontendConfig(BaseModel):
    """Configuration for the frontend"""

    backendUrl: str
    database: str | None
    showAppBar: bool
    noExternalRequests: bool
    enableAssembler: bool
    enablePlannotate: bool
    staticContentPath: str | None


BACKEND_URL = os.environ.get('BACKEND_URL', 'http://localhost:8000/')
DATABASE = os.environ.get('DATABASE', None)
SHOW_APP_BAR = parse_bool(os.environ.get('SHOW_APP_BAR', True))
NO_EXTERNAL_REQUESTS = parse_bool(os.environ.get('NO_EXTERNAL_REQUESTS', False))
ENABLE_ASSEMBLER = parse_bool(os.environ.get('ENABLE_ASSEMBLER', True))
ENABLE_PLANNOTATE = parse_bool(os.environ.get('ENABLE_PLANNOTATE', True))
STATIC_CONTENT_PATH = os.environ.get('STATIC_CONTENT_PATH', None)


frontend_config = FrontendConfig(
    backendUrl=BACKEND_URL,
    database=DATABASE,
    showAppBar=SHOW_APP_BAR,
    noExternalRequests=NO_EXTERNAL_REQUESTS,
    enableAssembler=ENABLE_ASSEMBLER,
    enablePlannotate=ENABLE_PLANNOTATE,
    staticContentPath=STATIC_CONTENT_PATH,
)
