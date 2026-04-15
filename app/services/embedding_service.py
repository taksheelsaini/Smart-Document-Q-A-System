# Copyright © Taksheel Saini. All rights reserved. | GitHub: https://github.com/taksheelsaini | LinkedIn: https://www.linkedin.com/in/taksheelsaini/"""
Embedding service: wraps SentenceTransformer as a process-level singleton.

Model choice — all-MiniLM-L6-v2:
  - 384-dimensional vectors keep FAISS indices small and search fast.
  - Strong semantic quality on English text retrieval benchmarks.
  - Runs efficiently on CPU; no GPU required.
  - ~22 MB model weight — downloads quickly and fits in a shared Docker volume.

L2 normalisation is applied to all embeddings so that inner-product search
in FAISS (IndexFlatIP) is equivalent to cosine similarity, giving scores
in [0, 1] that are easy to threshold.
"""

import logging
from functools import lru_cache

import numpy as np
from sentence_transformers import SentenceTransformer

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Process-level singleton that loads the model once and reuses it."""

    _instance: "EmbeddingService | None" = None

    def __new__(cls) -> "EmbeddingService":
        if cls._instance is None:
            instance = super().__new__(cls)
            instance._initialized = False
            cls._instance = instance
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        logger.info("Loading embedding model: %s", settings.EMBEDDING_MODEL)
        self._model = SentenceTransformer(settings.EMBEDDING_MODEL)
        self._initialized = True
        logger.info("Embedding model ready.")

    def embed(self, texts: list[str]) -> np.ndarray:
        """
        Embed a batch of texts.

        Returns an (N, D) float32 array with L2-normalised rows so that
        inner-product equals cosine similarity.
        """
        if not texts:
            return np.empty((0, settings.EMBEDDING_DIM), dtype=np.float32)
        return self._model.encode(
            texts,
            normalize_embeddings=True,
            batch_size=32,
            show_progress_bar=False,
        ).astype(np.float32)

    def embed_query(self, query: str) -> np.ndarray:
        """Embed a single query string. Returns shape (D,)."""
        return self.embed([query])[0]


@lru_cache(maxsize=1)
def get_embedding_service() -> EmbeddingService:
    """Return the process-singleton EmbeddingService, constructing it on first call."""
    return EmbeddingService()
