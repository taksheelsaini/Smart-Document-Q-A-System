# Copyright © Taksheel Saini. All rights reserved. | GitHub: https://github.com/taksheelsaini | LinkedIn: https://www.linkedin.com/in/taksheelsaini/"""
Background task: document ingestion pipeline.

Stages executed for each document:
  1. Mark status → PROCESSING
  2. Extract text (PDF or DOCX)
  3. Chunk text with overlap
  4. Persist chunks to PostgreSQL (assigns integer PKs used as FAISS IDs)
  5. Generate embeddings and build FAISS index
  6. Mark status → READY

On any failure the status is set to FAILED with a human-readable error_message
so the API's /status endpoint can surface the reason to the caller.

Retry behaviour:
  - Up to 2 automatic retries with a 30-second delay for transient errors
    (e.g. DB connection blip, temporary file-system issue).
  - Corrupted or empty documents are detected in stage 2/3 and immediately
    set to FAILED without retrying (there is no recovery from bad input).

Idempotency:
  - At task start, any existing chunks for the document are deleted so that
    a failed-then-retried document is processed from a clean state.
  - Documents not in PENDING or FAILED status are skipped to prevent
    duplicate processing if the same task is somehow enqueued twice.
"""

import logging
import uuid
from pathlib import Path

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.document import Chunk, Document, DocumentStatus
from app.services.document_processor import chunk_text, extract_text
from app.services.retrieval_service import build_and_save_index, delete_index
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    name="tasks.process_document",
)
def process_document(self, document_id: str) -> dict:
    doc_uuid = uuid.UUID(document_id)
    db = SessionLocal()

    try:
        document = db.query(Document).filter(Document.id == doc_uuid).first()
        if not document:
            logger.error("Document %s not found in database.", document_id)
            return {"status": "error", "message": "Document not found"}

        # Guard against duplicate task execution
        if document.status not in (DocumentStatus.PENDING, DocumentStatus.FAILED):
            logger.warning(
                "Document %s already in status '%s'. Skipping.",
                document_id,
                document.status.value,
            )
            return {"status": "skipped", "reason": document.status.value}

        # ── Stage 1: mark as in-progress ──────────────────────────────────
        document.status = DocumentStatus.PROCESSING
        document.error_message = None
        db.commit()

        # Clean up any artefacts from a previous failed attempt
        db.query(Chunk).filter(Chunk.document_id == doc_uuid).delete()
        delete_index(doc_uuid)
        db.commit()

        # ── Stage 2: extract text ──────────────────────────────────────────
        file_path = Path(settings.UPLOAD_DIR) / document.filename
        if not file_path.exists():
            raise FileNotFoundError(
                f"Uploaded file missing at {file_path}. "
                "It may have been removed before processing started."
            )

        logger.info(
            "Extracting text from '%s' (%s).",
            document.original_filename,
            document.file_type,
        )
        text = extract_text(file_path, document.file_type)

        if not text.strip():
            raise ValueError(
                "The document appears to be empty or its text could not be extracted. "
                "Image-only PDFs require OCR, which is not currently supported."
            )

        # ── Stage 3: chunk ─────────────────────────────────────────────────
        logger.info("Chunking document %s.", document_id)
        chunks_text = chunk_text(text, settings.CHUNK_SIZE, settings.CHUNK_OVERLAP)

        if not chunks_text:
            raise ValueError("No text chunks could be produced from the document.")

        # ── Stage 4: persist chunks (assigns integer PKs) ─────────────────
        chunk_objects = [
            Chunk(
                document_id=doc_uuid,
                content=chunk_content,
                chunk_index=i,
            )
            for i, chunk_content in enumerate(chunks_text)
        ]
        db.add_all(chunk_objects)
        db.flush()  # Populates chunk.id from the DB sequence

        # ── Stage 5: embed + index ─────────────────────────────────────────
        logger.info(
            "Building FAISS index for document %s (%d chunks).",
            document_id,
            len(chunk_objects),
        )
        build_and_save_index(doc_uuid, chunk_objects)

        # ── Stage 6: mark ready ────────────────────────────────────────────
        document.status = DocumentStatus.READY
        document.total_chunks = len(chunk_objects)
        db.commit()

        logger.info(
            "Document %s processed successfully — %d chunks indexed.",
            document_id,
            len(chunk_objects),
        )
        return {"status": "success", "chunks": len(chunk_objects)}

    except Exception as exc:
        db.rollback()
        logger.error(
            "Failed to process document %s: %s", document_id, exc, exc_info=True
        )

        # Persist failure reason so the API can surface it
        try:
            doc = db.query(Document).filter(Document.id == doc_uuid).first()
            if doc:
                doc.status = DocumentStatus.FAILED
                doc.error_message = str(exc)[:500]
                db.commit()
        except Exception:
            logger.error("Could not update document status to FAILED.", exc_info=True)

        # Retry only for potentially transient errors; corrupt documents will
        # fail again so we let those fall through after exhausting retries.
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)

        return {"status": "error", "message": str(exc)}

    finally:
        db.close()
