"""Indexing service: orchestrates text construction → embedding → vector store upsert."""

import logging

from src.analysis.schemas import MediaMetadataResult
from src.search.embedding_text import build_embedding_text
from src.search.embedder import Embedder
from src.search.vector_store import VectorStore

logger = logging.getLogger(__name__)


class IndexingService:
    """Orchestrates embedding generation and vector store updates."""

    def __init__(self, embedder: Embedder, vector_store: VectorStore) -> None:
        self._embedder = embedder
        self._vector_store = vector_store

    def index_media_item(
        self,
        media_item_id: str,
        user_id: str,
        original_filename: str,
        metadata_result: MediaMetadataResult,
    ) -> None:
        """Build embedding text, generate embedding, upsert to vector store."""
        text = build_embedding_text(metadata_result)
        embedding = self._embedder.embed_text(text)

        self._vector_store.upsert(
            media_item_id=media_item_id,
            embedding=embedding,
            metadata={
                "user_id": user_id,
                "title": metadata_result.title,
                "original_filename": original_filename,
            },
            document=text,
        )
        logger.info("Indexed media item %s", media_item_id)

    def remove_media_item(self, media_item_id: str) -> None:
        """Remove a media item from the vector store."""
        self._vector_store.delete(media_item_id)
        logger.info("Removed media item %s from index", media_item_id)
