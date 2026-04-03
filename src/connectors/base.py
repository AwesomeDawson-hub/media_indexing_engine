"""Abstract connector interface and remote object dataclass.

Connectors are responsible for:
  - validating their configuration
  - listing remote objects under a configured location
  - downloading individual object bytes

They delegate all ingest behavior (validation, dedup, storage, DB, quota,
analysis) to the existing upload service.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class RemoteObject:
    """Describes one remote object discovered during a sync listing."""

    key: str                                # remote path / object key
    version: str | None                     # ETag or version marker; None if not available
    last_modified_at: datetime | None       # remote last-modified timestamp
    size: int | None                        # byte size; None if not available


class ConnectorBase(ABC):
    """Abstract base class for all connector implementations."""

    @property
    @abstractmethod
    def connector_type(self) -> str:
        """Machine-readable connector type string, e.g. 's3_compatible'."""

    @abstractmethod
    async def list_objects(self, max_keys: int = 1000) -> list[RemoteObject]:
        """List remote objects.

        Args:
            max_keys: Maximum number of objects to return.

        Returns:
            List of RemoteObject instances.
        """

    @abstractmethod
    async def download_object(self, key: str) -> bytes:
        """Download the bytes of a single remote object.

        Args:
            key: The remote object key as returned by list_objects().

        Returns:
            Raw file bytes.
        """

    @abstractmethod
    async def validate(self) -> None:
        """Validate that the connector can reach its configured remote source.

        Raises:
            ConnectorValidationError: if connectivity or credential check fails.
        """


class ConnectorValidationError(Exception):
    """Raised when a connector cannot validate its configuration."""
