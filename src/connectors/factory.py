"""Connector factory (P7-002).

Single entry point for building a ``ConnectorBase`` implementation from a
``SourceConnector`` ORM row.  Keeps the sync service and other callers
decoupled from connector-specific construction details.
"""

from __future__ import annotations

from src.connectors.base import ConnectorBase
from src.models import SourceConnector


def build_connector(
    connector_row: SourceConnector,
    credentials: dict,
) -> ConnectorBase:
    """Return a ``ConnectorBase`` implementation for the given connector row.

    Args:
        connector_row: The ``SourceConnector`` ORM row for this source.
        credentials: Decrypted credentials dict from ``decrypt_credentials()``.

    Raises:
        ValueError: If ``connector_type`` is not recognized.
    """
    ctype = connector_row.connector_type

    if ctype == "s3_compatible":
        from src.connectors.s3_connector import build_s3_connector
        return build_s3_connector(
            bucket_name=connector_row.remote_container_id,
            credentials=credentials,
            region=connector_row.region,
            endpoint_url=connector_row.endpoint_url,
            prefix=connector_row.prefix,
        )

    if ctype == "google_drive":
        from src.config import settings
        from src.connectors.google_drive_connector import GoogleDriveConnector
        from src.connectors.google_drive_tokens import DriveTokenManager
        token_manager = DriveTokenManager(
            connector_row=connector_row,
            credentials=credentials,
            client_id=settings.google_drive.client_id,
            client_secret=settings.google_drive.client_secret,
            redirect_uri=settings.google_drive.redirect_uri,
        )
        return GoogleDriveConnector(
            token_manager=token_manager,
            folder_id=connector_row.target_folder_id,
        )

    raise ValueError(f"Unknown connector type: {ctype!r}")
