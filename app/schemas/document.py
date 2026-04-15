# Copyright © Taksheel Saini. All rights reserved. | GitHub: https://github.com/taksheelsaini | LinkedIn: https://www.linkedin.com/in/taksheelsaini/import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models.document import DocumentStatus


class DocumentResponse(BaseModel):
    id: uuid.UUID
    original_filename: str
    file_type: str
    file_size: int
    status: DocumentStatus
    error_message: Optional[str] = None
    total_chunks: int
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentList(BaseModel):
    documents: list[DocumentResponse]
    total: int


class DocumentStatusResponse(BaseModel):
    id: uuid.UUID
    status: DocumentStatus
    error_message: Optional[str] = None
    total_chunks: int
    message: str

    model_config = {"from_attributes": True}
