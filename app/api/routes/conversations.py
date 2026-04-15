# Copyright © Taksheel Saini. All rights reserved. | GitHub: https://github.com/taksheelsaini | LinkedIn: https://www.linkedin.com/in/taksheelsaini/import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from openai import APIError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.conversation import Conversation, Message, MessageRole
from app.models.document import Document, DocumentStatus
from app.schemas.conversation import (
    AnswerResponse,
    ConversationCreate,
    ConversationList,
    ConversationResponse,
    ConversationSummaryResponse,
    QuestionRequest,
    SourceChunk,
)
from app.services.llm_service import get_answer
from app.services.retrieval_service import search_index

router = APIRouter(prefix="/conversations", tags=["Conversations"])
logger = logging.getLogger(__name__)


@router.post(
    "",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a new conversation about a document",
    description=(
        "Creates a conversation linked to a specific document. "
        "The document must be in `ready` status. "
        "All subsequent questions in this conversation share the document's knowledge base."
    ),
)
def create_conversation(
    payload: ConversationCreate, db: Session = Depends(get_db)
) -> ConversationResponse:
    document = db.query(Document).filter(Document.id == payload.document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found."
        )
    if document.status != DocumentStatus.READY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Document is not ready for querying. "
                f"Current status: '{document.status.value}'. "
                "Wait until status is 'ready' before starting a conversation."
            ),
        )

    conversation = Conversation(
        document_id=payload.document_id,
        title=payload.title,
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation  # type: ignore[return-value]


@router.get(
    "",
    response_model=ConversationList,
    summary="List all conversations",
)
def list_conversations(db: Session = Depends(get_db)) -> ConversationList:
    conversations = (
        db.query(Conversation).order_by(Conversation.created_at.desc()).all()
    )
    return ConversationList(
        conversations=conversations,  # type: ignore[arg-type]
        total=len(conversations),
    )


@router.get(
    "/{conversation_id}",
    response_model=ConversationResponse,
    summary="Get a conversation with its full message history",
)
def get_conversation(
    conversation_id: uuid.UUID, db: Session = Depends(get_db)
) -> ConversationResponse:
    conversation = (
        db.query(Conversation).filter(Conversation.id == conversation_id).first()
    )
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found."
        )
    return conversation  # type: ignore[return-value]


@router.post(
    "/{conversation_id}/ask",
    response_model=AnswerResponse,
    summary="Ask a question within a conversation",
    description=(
        "Submits a natural-language question. The system:\n"
        "1. Embeds the question and retrieves the most relevant document excerpts via FAISS.\n"
        "2. Injects those excerpts as context into a prompt alongside the conversation history.\n"
        "3. Calls the LLM to produce a grounded answer.\n"
        "4. Persists both the question and answer to the conversation history.\n\n"
        "If no excerpts pass the relevance threshold, the LLM will explicitly state "
        "that the answer is not available in the document rather than hallucinating."
    ),
)
def ask_question(
    conversation_id: uuid.UUID,
    payload: QuestionRequest,
    db: Session = Depends(get_db),
) -> AnswerResponse:
    conversation = (
        db.query(Conversation).filter(Conversation.id == conversation_id).first()
    )
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found."
        )

    document = (
        db.query(Document).filter(Document.id == conversation.document_id).first()
    )
    if not document or document.status != DocumentStatus.READY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The associated document is not in a ready state.",
        )

    question = payload.question.strip()
    if not question:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Question cannot be empty.",
        )

    # ── Retrieval ─────────────────────────────────────────────────────────
    try:
        retrieved_chunks = search_index(
            document_id=conversation.document_id,
            query=question,
            db=db,
            top_k=settings.RETRIEVAL_TOP_K,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "The document's search index is missing. "
                "The document may need to be re-uploaded and reprocessed."
            ),
        ) from exc

    # ── Build history for prompt ──────────────────────────────────────────
    history = [
        {"role": msg.role.value, "content": msg.content}
        for msg in conversation.messages
    ]

    # ── LLM call ─────────────────────────────────────────────────────────
    try:
        answer = get_answer(
            context_chunks=retrieved_chunks,
            history=history,
            question=question,
        )
    except APIError as exc:
        logger.error(
            "OpenAI error for conversation %s: %s", conversation_id, exc
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "The language model service is temporarily unavailable. "
                "Please try again in a few moments."
            ),
        ) from exc

    # ── Persist user question + assistant answer ──────────────────────────
    source_data = [
        {
            "chunk_index": c["chunk_index"],
            "content": c["content"],
            "relevance_score": c["relevance_score"],
        }
        for c in retrieved_chunks
    ]

    user_msg = Message(
        conversation_id=conversation_id,
        role=MessageRole.USER,
        content=question,
    )
    assistant_msg = Message(
        conversation_id=conversation_id,
        role=MessageRole.ASSISTANT,
        content=answer,
        sources=source_data or None,
    )
    db.add_all([user_msg, assistant_msg])
    db.commit()
    db.refresh(assistant_msg)

    return AnswerResponse(
        message_id=assistant_msg.id,
        conversation_id=conversation_id,
        answer=answer,
        sources=[SourceChunk(**s) for s in source_data],
        model=settings.OPENAI_MODEL,
    )
