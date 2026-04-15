# Copyright © Taksheel Saini. All rights reserved. | GitHub: https://github.com/taksheelsaini | LinkedIn: https://www.linkedin.com/in/taksheelsaini/import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.document import Document, DocumentStatus
from app.schemas.document import DocumentList, DocumentResponse, DocumentStatusResponse
from app.services.retrieval_service import delete_index
from app.tasks.process_document import process_document

router = APIRouter(prefix="/documents", tags=["Documents"])

_ALLOWED_EXTENSIONS = {".pdf", ".docx"}


@router.post(
    "/upload",
    response_model=DocumentResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a document for processing",
    description=(
        "Upload a PDF or DOCX file. The file is stored immediately and a "
        "background Celery task handles text extraction, chunking, and "
        "vector indexing asynchronously. Poll `GET /documents/{id}/status` "
        "to check when the document is ready for querying."
    ),
)
async def upload_document(
    file: UploadFile = File(..., description="PDF or DOCX file to upload"),
    db: Session = Depends(get_db),
) -> DocumentResponse:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"Unsupported file type '{suffix}'. "
                f"Accepted types: {sorted(_ALLOWED_EXTENSIONS)}"
            ),
        )

    content = await file.read()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    if len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file is empty.",
        )
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size exceeds the {settings.MAX_UPLOAD_SIZE_MB} MB limit.",
        )

    # Persist to storage with a UUID-based filename to avoid collisions
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)

    document_id = uuid.uuid4()
    stored_filename = f"{document_id}{suffix}"
    (upload_dir / stored_filename).write_bytes(content)
    original_filename = Path(file.filename or stored_filename).name

    document = Document(
        id=document_id,
        filename=stored_filename,
        original_filename=original_filename,
        file_type=suffix.lstrip("."),
        file_size=len(content),
        status=DocumentStatus.PENDING,
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    # Dispatch background task — upload returns immediately
    process_document.delay(str(document_id))

    return document  # type: ignore[return-value]


@router.get(
    "",
    response_model=DocumentList,
    summary="List all uploaded documents",
)
def list_documents(db: Session = Depends(get_db)) -> DocumentList:
    documents = db.query(Document).order_by(Document.created_at.desc()).all()
    return DocumentList(documents=documents, total=len(documents))  # type: ignore[arg-type]


@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="Get document details",
)
def get_document(
    document_id: uuid.UUID, db: Session = Depends(get_db)
) -> DocumentResponse:
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found."
        )
    return document  # type: ignore[return-value]


@router.get(
    "/{document_id}/status",
    response_model=DocumentStatusResponse,
    summary="Poll document processing status",
    description=(
        "Returns the current processing status of a document. "
        "Status transitions: pending → processing → ready (or failed). "
        "A document must be in `ready` status before conversations can be started."
    ),
)
def get_document_status(
    document_id: uuid.UUID, db: Session = Depends(get_db)
) -> DocumentStatusResponse:
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found."
        )

    status_messages = {
        DocumentStatus.PENDING: "Document is queued for processing.",
        DocumentStatus.PROCESSING: "Document is currently being processed.",
        DocumentStatus.READY: (
            f"Document is ready. {document.total_chunks} chunks indexed and searchable."
        ),
        DocumentStatus.FAILED: f"Processing failed: {document.error_message}",
    }

    return DocumentStatusResponse(
        id=document.id,
        status=document.status,
        error_message=document.error_message,
        total_chunks=document.total_chunks,
        message=status_messages[document.status],
    )


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document and all associated data",
    description=(
        "Permanently removes the document, its uploaded file, FAISS index, "
        "all chunks, conversations, and messages. This action is irreversible."
    ),
)
def delete_document(document_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found."
        )

    delete_index(document_id)

    file_path = Path(settings.UPLOAD_DIR) / document.filename
    if file_path.exists():
        file_path.unlink()

    db.delete(document)
    db.commit()
