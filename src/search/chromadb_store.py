"""ChromaDB vector store implementation (ADR-006)."""

import chromadb

from src.config import settings
from src.search.models import SearchHit


class ChromaDBVectorStore:
    """Vector store backed by ChromaDB with persistent storage."""

    def __init__(
        self,
        persist_directory: str | None = None,
        collection_name: str | None = None,
    ) -> None:
        persist_dir = persist_directory or settings.search.persist_directory
        coll_name = collection_name or settings.search.collection_name

        self._client = chromadb.PersistentClient(path=persist_dir)
        self._collection = self._client.get_or_create_collection(
            name=coll_name,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert(
        self,
        media_item_id: str,
        embedding: list[float],
        metadata: dict,
        document: str,
    ) -> None:
        self._collection.upsert(
            ids=[media_item_id],
            embeddings=[embedding],
            metadatas=[metadata],
            documents=[document],
        )

    def search(
        self,
        query_embedding: list[float],
        user_id: str,
        top_k: int = 20,
    ) -> list[SearchHit]:
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where={"user_id": user_id},
        )

        hits: list[SearchHit] = []
        if results["ids"] and results["ids"][0]:
            ids = results["ids"][0]
            distances = results["distances"][0] if results["distances"] else [0.0] * len(ids)
            metadatas = results["metadatas"][0] if results["metadatas"] else [{}] * len(ids)

            for item_id, distance, meta in zip(ids, distances, metadatas):
                # ChromaDB cosine distance: 0 = identical, 2 = opposite
                # Convert to similarity score: 1 - (distance / 2) → 0.0 to 1.0
                score = max(0.0, 1.0 - (distance / 2.0))
                hits.append(SearchHit(
                    media_item_id=item_id,
                    score=round(score, 4),
                    title=meta.get("title"),
                    original_filename=meta.get("original_filename"),
                ))

        return hits

    def delete(self, media_item_id: str) -> None:
        self._collection.delete(ids=[media_item_id])

    def delete_items(self, media_ids: list[str]) -> None:
        if media_ids:
            self._collection.delete(ids=media_ids)

    def count(self) -> int:
        return self._collection.count()
