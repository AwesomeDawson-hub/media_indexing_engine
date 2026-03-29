"""Embedding generation using sentence-transformers."""

from sentence_transformers import SentenceTransformer

from src.config import settings


class Embedder:
    """Wrapper around SentenceTransformer for text embedding.

    Model is loaded once at init and reused across calls.
    """

    def __init__(self, model_name: str | None = None) -> None:
        self._model = SentenceTransformer(model_name or settings.search.embedding_model)

    def embed_text(self, text: str) -> list[float]:
        """Encode a single text to a float vector."""
        return self._model.encode(text, convert_to_numpy=True).tolist()

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Batch encode multiple texts."""
        embeddings = self._model.encode(texts, convert_to_numpy=True)
        return [e.tolist() for e in embeddings]
