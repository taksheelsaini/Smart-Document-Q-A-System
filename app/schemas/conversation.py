# Copyright © Taksheel Saini. All rights reserved. | GitHub: https://github.com/taksheelsaini | LinkedIn: https://www.linkedin.com/in/taksheelsaini/import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.conversation import MessageRole


class ConversationCreate(BaseModel):
    document_id: uuid.UUID
    title: Optional[str] = Field(default=None, max_length=200)


class SourceChunk(BaseModel):
    chunk_index: int
    content: str
    relevance_score: float


class MessageResponse(BaseModel):
    id: uuid.UUID
    role: MessageRole
    content: str
    sources: Optional[list[SourceChunk]] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationSummaryResponse(BaseModel):
    """Lightweight view used in list responses — omits messages to avoid over-fetching."""

    id: uuid.UUID
    document_id: uuid.UUID
    title: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationResponse(BaseModel):
    """Full view including the complete message history."""

    id: uuid.UUID
    document_id: uuid.UUID
    title: Optional[str] = None
    created_at: datetime
    messages: list[MessageResponse] = []

    model_config = {"from_attributes": True}


class ConversationList(BaseModel):
    conversations: list[ConversationSummaryResponse]
    total: int


class QuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)


class AnswerResponse(BaseModel):
    message_id: uuid.UUID
    conversation_id: uuid.UUID
    answer: str
    sources: list[SourceChunk]
    model: str
