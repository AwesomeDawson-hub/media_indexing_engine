"""Rebuild the entire vector store from the database.

Proves the ADR-006 "derived store" principle: if ChromaDB data is lost,
it can be fully regenerated from the database (the system of record).

Usage:
    python -m scripts.rebuild_vector_store
"""

import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import async_session, create_tables
from src.models import MediaItem, MediaMetadata
from src.search.chromadb_store import ChromaDBVectorStore
from src.search.embedder import Embedder
from src.search.embedding_text import build_embedding_text_from_db


async def rebuild() -> None:
    await create_tables()

    embedder = Embedder()
    vector_store = ChromaDBVectorStore()

    print(f"Embedding model: {settings.search.embedding_model}")
    print(f"Vector store: {settings.search.persist_directory}/{settings.search.collection_name}")
    print()

    async with async_session() as db:
        # Load all analyzed media items with their metadata
        result = await db.execute(
            select(MediaMetadata, MediaItem)
            .join(MediaItem, MediaMetadata.media_item_id == MediaItem.id)
        )
        rows = result.all()

        if not rows:
            print("No analyzed media items found. Nothing to rebuild.")
            return

        print(f"Found {len(rows)} analyzed media items. Rebuilding...")

        for i, (meta, item) in enumerate(rows, 1):
            text = build_embedding_text_from_db(meta)
            embedding = embedder.embed_text(text)
            vector_store.upsert(
                media_item_id=item.id,
                embedding=embedding,
                metadata={
                    "user_id": item.user_id,
                    "title": meta.title,
                    "original_filename": item.original_filename,
                },
                document=text,
            )
            print(f"  [{i}/{len(rows)}] {item.original_filename} — {meta.title}")

    print()
    print(f"Rebuild complete. Vector store count: {vector_store.count()}")


if __name__ == "__main__":
    asyncio.run(rebuild())
