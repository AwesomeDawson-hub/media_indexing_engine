"""File storage abstraction and local filesystem implementation (ADR-004, ADR-006)."""

import os
from abc import ABC, abstractmethod
from pathlib import Path

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
