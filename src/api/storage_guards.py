"""Source-aware original-access guards (P9-002 / ADR-031).

Shared helpers used across API routes and internal pipelines to produce
consistent controlled errors when a MediaItem's original file is not retained
in app storage.

storage_mode semantics:
    'full'         — original retained in app storage (browser uploads)
    'preview_only' — original was stored then deleted after confirmed thumbnail
    'reference'    — original was never stored (connector-ingested, P9-001)

Per ADR-031 operator direction: the interim default for any surface that cannot
access the original is a controlled 409 'original_at_source' response.
"""
from __future__ import annotations

from fastapi import HTTPException

from src.models import MediaItem

_ORIGINAL_AT_SOURCE_DETAIL = {
    "error_code": "original_at_source",
    "message": (
        "The original file is held at the source connector, not in app storage. "
        "Use the source connector to access the original."
    ),
}


def original_is_accessible(item: MediaItem) -> bool:
    """Return True only when the original file exists in app storage."""
    return item.storage_mode == "full" and bool(item.storage_path)


def assert_original_accessible(item: MediaItem) -> None:
    """Raise HTTP 409 original_at_source if the original is not in app storage.

    Safe to call from any API route that requires original bytes.
    Does NOT raise for full-mode items with a storage_path.
    """
    if not original_is_accessible(item):
        raise HTTPException(
            status_code=409,
            detail=_ORIGINAL_AT_SOURCE_DETAIL,
        )
