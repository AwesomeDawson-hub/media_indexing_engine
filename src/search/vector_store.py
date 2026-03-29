"""Abstract vector store interface for semantic search."""

from typing import Protocol

from src.search.models import SearchHit


class VectorStore(Protocol):
    """Abstract interface for vector stores. Implementations can target ChromaDB, Qdrant, etc."""

    def upsert(
        self,
        media_item_id: str,
        embedding: list[float],
        metadata: dict,
        document: str,
    ) -> None:
        """Insert or update a vector entry."""
        ...

    def search(
        self,
        query_embedding: list[float],
        user_id: str,
        top_k: int = 20,
    ) -> list[SearchHit]:
        """Search for similar vectors, filtered by user_id."""
        ...

    def delete(self, media_item_id: str) -> None:
        """Remove a vector entry by media item ID."""
        ...

    def delete_items(self, media_ids: list[str]) -> None:
        """Remove multiple vector entries by media item IDs."""
        ...

    def count(self) -> int:
        """Return the total number of entries in the store."""
        ...
