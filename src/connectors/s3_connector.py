"""S3-compatible connector implementation.

Supports AWS S3 and any S3-compatible provider (MinIO, Backblaze B2, etc.)
by exposing an optional endpoint_url override.

Credentials (access_key_id, secret_access_key) are passed in at construction
time — they have already been decrypted by the caller from the encrypted DB
payload. This module never reads or writes the encrypted store directly.

S3 operations use boto3 via run_in_executor to avoid blocking the async event
loop. boto3 is an optional production dependency; import errors at call time
produce a clear message.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from functools import partial

from src.connectors.base import ConnectorBase, ConnectorValidationError, RemoteObject
from src.config import settings

logger = logging.getLogger(__name__)

# File extensions/MIME types accepted by the upload pipeline.
_SUPPORTED_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif",
    ".bmp", ".gif", ".avif",
})


def _is_supported_key(key: str) -> bool:
    _, ext = os.path.splitext(key.lower())
    return ext in _SUPPORTED_EXTENSIONS


class S3Connector(ConnectorBase):
    """Lists and downloads objects from an S3-compatible bucket."""

    def __init__(
        self,
        *,
        bucket_name: str,
        access_key_id: str,
        secret_access_key: str,
        region: str | None = None,
        endpoint_url: str | None = None,
        prefix: str | None = None,
    ) -> None:
        self._bucket = bucket_name
        self._prefix = prefix or ""
        self._region = region or "us-east-1"
        self._endpoint_url = endpoint_url or None
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key

    @property
    def connector_type(self) -> str:
        return "s3_compatible"

    def _make_client(self):
        """Create a boto3 S3 client. Import is deferred to surface missing dep clearly."""
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError(
                "boto3 is required for S3-compatible connectors. "
                "Install it with: pip install boto3"
            ) from exc

        kwargs: dict = {
            "aws_access_key_id": self._access_key_id,
            "aws_secret_access_key": self._secret_access_key,
            "region_name": self._region,
        }
        if self._endpoint_url:
            kwargs["endpoint_url"] = self._endpoint_url

        return boto3.client("s3", **kwargs)

    def _sync_list_objects(self, max_keys: int) -> list[RemoteObject]:
        """Synchronous list — called via run_in_executor."""
        client = self._make_client()
        results: list[RemoteObject] = []
        paginator = client.get_paginator("list_objects_v2")
        paginate_kwargs: dict = {"Bucket": self._bucket, "PaginationConfig": {"MaxItems": max_keys}}
        if self._prefix:
            paginate_kwargs["Prefix"] = self._prefix

        for page in paginator.paginate(**paginate_kwargs):
            for obj in page.get("Contents", []):
                key: str = obj["Key"]
                if not _is_supported_key(key):
                    continue
                # Skip prefix-only "directory" entries
                if key.endswith("/"):
                    continue
                last_mod = obj.get("LastModified")
                if last_mod and last_mod.tzinfo is None:
                    last_mod = last_mod.replace(tzinfo=timezone.utc)
                results.append(RemoteObject(
                    key=key,
                    display_name=os.path.basename(key) or key,
                    version=obj.get("ETag", "").strip('"') or None,
                    last_modified_at=last_mod,
                    size=obj.get("Size"),
                ))
                if len(results) >= max_keys:
                    return results
        return results

    def _sync_download_object(self, key: str) -> bytes:
        """Synchronous download — called via run_in_executor."""
        client = self._make_client()
        response = client.get_object(Bucket=self._bucket, Key=key)
        return response["Body"].read()

    def _sync_validate(self) -> None:
        """Synchronous validate — called via run_in_executor."""
        client = self._make_client()
        # head_bucket checks both credentials and bucket accessibility
        client.head_bucket(Bucket=self._bucket)

    async def list_objects(self, max_keys: int | None = None) -> list[RemoteObject]:
        if max_keys is None:
            max_keys = settings.connector.max_objects_per_sync
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(self._sync_list_objects, max_keys))

    async def download_object(self, key: str) -> bytes:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(self._sync_download_object, key))

    async def validate(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._sync_validate)
        except Exception as exc:
            raise ConnectorValidationError(f"S3 validation failed: {exc}") from exc


def build_s3_connector(
    *,
    bucket_name: str,
    credentials: dict,
    region: str | None = None,
    endpoint_url: str | None = None,
    prefix: str | None = None,
) -> S3Connector:
    """Construct an S3Connector from decrypted credential dict.

    Args:
        bucket_name: S3 bucket name (plain column from SourceConnector).
        credentials: Decrypted dict containing 'access_key_id' and 'secret_access_key'.
        region: Optional region override.
        endpoint_url: Optional S3-compatible endpoint URL.
        prefix: Optional object key prefix filter.
    """
    return S3Connector(
        bucket_name=bucket_name,
        access_key_id=credentials["access_key_id"],
        secret_access_key=credentials["secret_access_key"],
        region=region,
        endpoint_url=endpoint_url,
        prefix=prefix,
    )
