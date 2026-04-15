# Copyright © Taksheel Saini. All rights reserved. | GitHub: https://github.com/taksheelsaini | LinkedIn: https://www.linkedin.com/in/taksheelsaini/"""
Retrieval service: manages per-document FAISS indices.

Index design — IndexIDMap(IndexFlatIP):
  - FlatIP performs exact (exhaustive) nearest-neighbour search.
    For typical document sizes (<5,000 chunks) this is fast enough (<5 ms)
    and avoids the recall loss of approximate indices (IVF, HNSW).
  - IndexIDMap lets us assign arbitrary int64 IDs — we use the chunk's
    database primary key directly, eliminating any separate ID→chunk
    mapping file and making post-search DB lookups a single IN query.
  - One .faiss file per document: clean deletion, no cross-document
    contamination, and easy to inspect or migrate.

Score threshold:
  If every retrieved chunk scores below RETRIEVAL_SCORE_THRESHOLD the function
  returns an empty list, signalling to the LLM layer that no relevant context
  was found and it should decline to answer rather than hallucinate.
"""

import logging
import uuid
from pathlib import Path

import faiss
import numpy as np
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Chunk
from app.services.embedding_service import get_embedding_service

logger = logging.getLogger(__name__)


def _index_path(document_id: uuid.UUID) -> Path:
    return Path(settings.INDEX_DIR) / f"{document_id}.faiss"


def build_and_save_index(document_id: uuid.UUID, chunks: list[Chunk]) -> None:
    """
    Build a FAISS FlatIP index for *chunks* and persist it to disk.

    Embeddings are generated in a single batched call and the chunk DB IDs
    are registered as FAISS vector IDs via IndexIDMap.
    """
    embedding_service = get_embedding_service()
    texts = [chunk.content for chunk in chunks]
    embeddings = embedding_service.embed(texts)  # (N, D) float32, L2-normalised

    dim = embeddings.shape[1]
    flat = faiss.IndexFlatIP(dim)
    index = faiss.IndexIDMap(flat)

    chunk_ids = np.array([chunk.id for chunk in chunks], dtype=np.int64)
    index.add_with_ids(embeddings, chunk_ids)

    index_file = _index_path(document_id)
    index_file.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(index_file))

    logger.info(
        "FAISS index built for document %s — %d vectors, dim=%d.",
        document_id,
        len(chunks),
        dim,
    )


def search_index(
    document_id: uuid.UUID,
    query: str,
    db: Session,
    top_k: int | None = None,
) -> list[dict]:
    """
    Retrieve the most relevant chunks for *query* from a document's index.

    Returns a list of dicts (chunk_index, content, relevance_score), ordered
    by descending relevance. Chunks below RETRIEVAL_SCORE_THRESHOLD are excluded.
    An empty list means "no relevant context found."
    """
    top_k = top_k or settings.RETRIEVAL_TOP_K
    index_file = _index_path(document_id)

    if not index_file.exists():
        raise FileNotFoundError(
            f"No FAISS index found for document {document_id}. "
            "The document may still be processing or failed during indexing."
        )

    embedding_service = get_embedding_service()
    query_vec = embedding_service.embed_query(query).reshape(1, -1)

    index = faiss.read_index(str(index_file))
    scores, ids = index.search(query_vec, top_k)

    # FAISS fills unused slots with id=-1 and score=-inf; filter both out.
    valid = [
        (int(chunk_id), float(score))
        for chunk_id, score in zip(ids[0], scores[0])
        if chunk_id != -1 and score >= settings.RETRIEVAL_SCORE_THRESHOLD
    ]

    if not valid:
        logger.info(
            "No chunks above threshold %.2f for document %s.",
            settings.RETRIEVAL_SCORE_THRESHOLD,
            document_id,
        )
        return []

    chunk_id_list = [r[0] for r in valid]
    score_map = {r[0]: r[1] for r in valid}

    chunks = db.query(Chunk).filter(Chunk.id.in_(chunk_id_list)).all()
    chunk_map = {chunk.id: chunk for chunk in chunks}

    return [
        {
            "chunk_index": chunk_map[cid].chunk_index,
            "content": chunk_map[cid].content,
            "relevance_score": round(score_map[cid], 4),
        }
        for cid in chunk_id_list
        if cid in chunk_map
    ]


def delete_index(document_id: uuid.UUID) -> None:
    """Remove the FAISS index file for a document, if it exists."""
    index_file = _index_path(document_id)
    if index_file.exists():
        index_file.unlink()
        logger.info("Deleted FAISS index for document %s.", document_id)
