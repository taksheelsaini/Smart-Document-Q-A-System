"""
Pytest configuration and shared fixtures.

Heavy ML dependencies (SentenceTransformer, FAISS) are mocked at import time.
SQLite in-memory uses StaticPool so all connections share one DB instance.
"""

import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# ── Mock heavy deps before any app import ────────────────────────────────────
mock_st_module = MagicMock()
mock_st_instance = MagicMock()
mock_st_instance.encode.return_value = np.random.rand(1, 384).astype(np.float32)
mock_st_module.SentenceTransformer.return_value = mock_st_instance
sys.modules.setdefault("sentence_transformers", mock_st_module)

mock_faiss = MagicMock()
mock_index = MagicMock()
mock_index.search.return_value = (np.array([[0.9, 0.7]]), np.array([[-1, -1]]))
mock_faiss.IndexFlatIP.return_value = MagicMock()
mock_faiss.IndexIDMap.return_value = mock_index
mock_faiss.read_index.return_value = mock_index
sys.modules.setdefault("faiss", mock_faiss)

# Now safe to import app modules
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app

# StaticPool: all connections share ONE in-memory SQLite database
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_database():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def uploaded_document(client, db, tmp_path, monkeypatch):
    """Upload a real PDF, then mark READY for conversation tests."""
    from app.models.document import Document, DocumentStatus

    monkeypatch.setattr("app.api.routes.documents.settings.UPLOAD_DIR", str(tmp_path))
    sample = Path(__file__).parent.parent / "sample_docs" / "ai_overview.pdf"

    with patch("app.tasks.process_document.process_document.delay"):
        with open(sample, "rb") as f:
            response = client.post(
                "/api/v1/documents/upload",
                files={"file": ("ai_overview.pdf", f, "application/pdf")},
            )

    assert response.status_code == 202, response.text
    doc_id = uuid.UUID(response.json()["id"])

    doc = db.query(Document).filter(Document.id == doc_id).first()
    doc.status = DocumentStatus.READY
    doc.total_chunks = 10
    db.commit()
    return doc
