"""S3-compatible object storage helpers for OpenCloning DB runtime assets."""

from __future__ import annotations

import uuid
from contextlib import closing

import boto3
from botocore.client import BaseClient, Config as BotoConfig
from botocore.exceptions import ClientError

from opencloning_db.config import Config, get_config

_storage: 'ObjectStorage | None' = None


def is_missing_object_error(exc: ClientError) -> bool:
    error_code = exc.response.get('Error', {}).get('Code')
    return error_code in {'404', 'NoSuchKey', 'NoSuchBucket'}


def _new_object_key(prefix: str, extension: str) -> str:
    normalized_extension = extension if extension.startswith('.') or extension == '' else f'.{extension}'
    return f'{prefix}{uuid.uuid4().hex}{normalized_extension}'


class ObjectStorage:
    """Thin S3-compatible wrapper used by runtime file flows."""

    def __init__(self, config: Config):
        self.config = config
        self.bucket = config.object_storage_bucket
        self.sequence_prefix = config.sequence_objects_prefix
        self.sequencing_prefix = config.sequencing_objects_prefix
        self._client = boto3.client(
            's3',
            endpoint_url=config.object_storage_endpoint_url,
            aws_access_key_id=config.object_storage_access_key_id,
            aws_secret_access_key=config.object_storage_secret_access_key,
            region_name=config.object_storage_region,
            config=BotoConfig(s3={'addressing_style': 'path' if config.object_storage_force_path_style else 'auto'}),
        )

    @property
    def client(self) -> BaseClient:
        return self._client

    def validate_bucket_exists(self) -> None:
        self.client.head_bucket(Bucket=self.bucket)

    def new_sequence_key(self, extension: str = '.gb') -> str:
        return _new_object_key(self.sequence_prefix, extension)

    def new_sequencing_key(self, extension: str) -> str:
        return _new_object_key(self.sequencing_prefix, extension)

    def write_text(self, key: str, content: str, *, content_type: str = 'text/plain; charset=utf-8') -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=content.encode('utf-8'), ContentType=content_type)

    def write_bytes(self, key: str, content: bytes, *, content_type: str = 'application/octet-stream') -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=content, ContentType=content_type)

    def read_text(self, key: str) -> str:
        return self.read_bytes(key).decode('utf-8')

    def read_bytes(self, key: str) -> bytes:
        data, _ = self.read_bytes_with_content_type(key)
        return data

    def read_bytes_with_content_type(self, key: str) -> tuple[bytes, str | None]:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        with closing(response['Body']) as body:
            return body.read(), response.get('ContentType')

    def delete_object(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def delete_objects(self, keys: list[str]) -> None:
        if not keys:
            return
        chunks = [keys[i : i + 1000] for i in range(0, len(keys), 1000)]
        for chunk in chunks:
            self.client.delete_objects(
                Bucket=self.bucket,
                Delete={'Objects': [{'Key': key} for key in chunk], 'Quiet': True},
            )

    def list_keys(self, prefix: str) -> list[str]:
        paginator = self.client.get_paginator('list_objects_v2')
        keys: list[str] = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            keys.extend(obj['Key'] for obj in page.get('Contents', []))
        return keys

    def clear_prefix(self, prefix: str) -> None:
        self.delete_objects(self.list_keys(prefix))


def _peek_storage() -> ObjectStorage | None:
    return _storage


def get_storage() -> ObjectStorage:
    global _storage
    if _storage is None or _storage.config != get_config():
        _storage = ObjectStorage(get_config())
    return _storage


def set_storage(storage: ObjectStorage | None) -> None:
    global _storage
    _storage = storage
