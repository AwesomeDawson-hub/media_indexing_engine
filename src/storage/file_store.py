"""File storage abstraction, local filesystem implementation, and S3 implementation (ADR-004, ADR-006)."""

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger(__name__)

# Max filename length on disk to avoid Windows MAX_PATH (260 char) issues.
# user_id (36) + hash (64) + separators (~10) + root path (~80) = ~190 chars for the path prefix.
# Leaves ~70 chars for the filename.
_MAX_FILENAME_LEN = 70


def _safe_filename(name: str) -> str:
    """Truncate filename if it would exceed path limits, preserving the extension."""
    if len(name) <= _MAX_FILENAME_LEN:
        return name
    base, ext = os.path.splitext(name)
    max_base = _MAX_FILENAME_LEN - len(ext)
    return base[:max_base] + ext


class FileStore(ABC):
    """Abstract interface for file storage. Implementations can target local disk, S3, etc."""

    @abstractmethod
    async def save(
        self, user_id: str, content_hash: str, original_filename: str, file_bytes: bytes
    ) -> str:
        """Save file and return the relative storage path."""
        ...

    @abstractmethod
    async def read(self, storage_path: str) -> bytes:
        """Read file bytes from storage."""
        ...

    @abstractmethod
    async def exists(self, storage_path: str) -> bool:
        ...

    @abstractmethod
    async def delete(self, storage_path: str) -> None:
        ...


class LocalFileStore(FileStore):
    """Store files on local filesystem using content-addressed paths.

    Layout: {root}/{user_id}/{content_hash}/{original_filename}
    """

    def __init__(self, root_dir: str) -> None:
        self._root = Path(root_dir).resolve()

    async def save(
        self, user_id: str, content_hash: str, original_filename: str, file_bytes: bytes
    ) -> str:
        disk_filename = _safe_filename(original_filename)
        relative_path = f"{user_id}/{content_hash}/{disk_filename}"
        full_path = self._root / relative_path

        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(file_bytes)

        return relative_path

    async def read(self, storage_path: str) -> bytes:
        return (self._root / storage_path).read_bytes()

    async def exists(self, storage_path: str) -> bool:
        return (self._root / storage_path).exists()

    async def delete(self, storage_path: str) -> None:
        target = self._root / storage_path
        if target.exists():
            target.unlink()


class S3FileStore(FileStore):
    """Store files in an S3-compatible object store (AWS S3, MinIO, etc.).

    Layout: s3://{bucket}/{user_id}/{content_hash}/{filename}

    AWS credentials must be provided via environment variables:
        AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY (and optionally AWS_SESSION_TOKEN).
    They are NEVER read from config files.
    """

    def __init__(self, bucket: str, region: str = "us-east-1", endpoint_url: str = "") -> None:
        self._bucket = bucket
        self._region = region
        self._endpoint_url = endpoint_url or None

    def _client(self):
        """Create a boto3 S3 client. Called per-operation to avoid event-loop issues."""
        try:
            import boto3  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "boto3 is required for S3 storage. Install it with: pip install boto3"
            ) from exc

        kwargs: dict = {"region_name": self._region}
        if self._endpoint_url:
            kwargs["endpoint_url"] = self._endpoint_url
        return boto3.client("s3", **kwargs)

    def _key(self, storage_path: str) -> str:
        """storage_path is already {user_id}/{content_hash}/{filename} — use as S3 key."""
        return storage_path

    async def save(
        self, user_id: str, content_hash: str, original_filename: str, file_bytes: bytes
    ) -> str:
        disk_filename = _safe_filename(original_filename)
        storage_path = f"{user_id}/{content_hash}/{disk_filename}"
        key = self._key(storage_path)

        def _put() -> None:
            self._client().put_object(Bucket=self._bucket, Key=key, Body=file_bytes)

        await asyncio.get_event_loop().run_in_executor(None, _put)
        return storage_path

    async def read(self, storage_path: str) -> bytes:
        key = self._key(storage_path)

        def _get() -> bytes:
            response = self._client().get_object(Bucket=self._bucket, Key=key)
            return response["Body"].read()

        return await asyncio.get_event_loop().run_in_executor(None, _get)

    async def exists(self, storage_path: str) -> bool:
        key = self._key(storage_path)

        def _head() -> bool:
            try:
                self._client().head_object(Bucket=self._bucket, Key=key)
                return True
            except Exception:
                return False

        return await asyncio.get_event_loop().run_in_executor(None, _head)

    async def delete(self, storage_path: str) -> None:
        key = self._key(storage_path)

        def _delete() -> None:
            try:
                self._client().delete_object(Bucket=self._bucket, Key=key)
            except Exception:
                logger.warning("S3FileStore.delete: failed to delete key %s", key)

        await asyncio.get_event_loop().run_in_executor(None, _delete)


def get_file_store(storage_config) -> FileStore:
    """Factory: return the correct FileStore based on storage config."""
    if storage_config.provider == "s3":
        if not storage_config.s3_bucket:
            raise RuntimeError(
                "storage.s3_bucket must be set when storage.provider is 's3'."
            )
        return S3FileStore(
            bucket=storage_config.s3_bucket,
            region=storage_config.s3_region,
            endpoint_url=storage_config.s3_endpoint_url,
        )
    return LocalFileStore(storage_config.local_path)
