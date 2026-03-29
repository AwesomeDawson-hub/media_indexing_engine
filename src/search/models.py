"""Data models for search results."""

from dataclasses import dataclass


@dataclass
class SearchHit:
    """A single search result from the vector store."""
    media_item_id: str
    score: float  # 0.0–1.0, higher = more relevant
    title: str | None = None
    original_filename: str | None = None
