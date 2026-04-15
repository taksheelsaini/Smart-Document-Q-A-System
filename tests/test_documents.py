"""Tests for document management endpoints."""

from pathlib import Path
from unittest.mock import patch

import pytest


SAMPLE_PDF = Path(__file__).parent.parent / "sample_docs" / "ai_overview.pdf"
SAMPLE_DOCX = Path(__file__).parent.parent / "sample_docs" / "python_programming_guide.docx"


class TestDocumentUpload:
    def test_upload_pdf_returns_202(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr("app.api.routes.documents.settings.UPLOAD_DIR", str(tmp_path))
        with patch("app.tasks.process_document.process_document.delay"):
            with open(SAMPLE_PDF, "rb") as f:
                resp = client.post(
                    "/api/v1/documents/upload",
                    files={"file": ("ai_overview.pdf", f, "application/pdf")},
                )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "pending"
        assert data["original_filename"] == "ai_overview.pdf"
        assert data["file_type"] == "pdf"
        assert data["total_chunks"] == 0

    def test_upload_docx_returns_202(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr("app.api.routes.documents.settings.UPLOAD_DIR", str(tmp_path))
        with patch("app.tasks.process_document.process_document.delay"):
            with open(SAMPLE_DOCX, "rb") as f:
                resp = client.post(
                    "/api/v1/documents/upload",
                    files={"file": ("guide.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
                )
        assert resp.status_code == 202

    def test_upload_unsupported_type_returns_415(self, client):
        resp = client.post(
            "/api/v1/documents/upload",
            files={"file": ("bad.txt", b"hello", "text/plain")},
        )
        assert resp.status_code == 415

    def test_upload_empty_file_returns_400(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr("app.api.routes.documents.settings.UPLOAD_DIR", str(tmp_path))
        resp = client.post(
            "/api/v1/documents/upload",
            files={"file": ("empty.pdf", b"", "application/pdf")},
        )
        assert resp.status_code == 400

    def test_upload_dispatches_celery_task(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr("app.api.routes.documents.settings.UPLOAD_DIR", str(tmp_path))
        with patch("app.tasks.process_document.process_document.delay") as mock_delay:
            with open(SAMPLE_PDF, "rb") as f:
                resp = client.post(
                    "/api/v1/documents/upload",
                    files={"file": ("ai_overview.pdf", f, "application/pdf")},
                )
        assert resp.status_code == 202
        mock_delay.assert_called_once()


class TestDocumentListing:
    def test_list_empty(self, client):
        resp = client.get("/api/v1/documents")
        assert resp.status_code == 200
        assert resp.json() == {"documents": [], "total": 0}

    def test_list_after_upload(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr("app.api.routes.documents.settings.UPLOAD_DIR", str(tmp_path))
        with patch("app.tasks.process_document.process_document.delay"):
            with open(SAMPLE_PDF, "rb") as f:
                client.post(
                    "/api/v1/documents/upload",
                    files={"file": ("ai_overview.pdf", f, "application/pdf")},
                )
        resp = client.get("/api/v1/documents")
        data = resp.json()
        assert data["total"] == 1
        assert data["documents"][0]["original_filename"] == "ai_overview.pdf"


class TestDocumentStatus:
    def test_status_pending(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr("app.api.routes.documents.settings.UPLOAD_DIR", str(tmp_path))
        with patch("app.tasks.process_document.process_document.delay"):
            with open(SAMPLE_PDF, "rb") as f:
                upload_resp = client.post(
                    "/api/v1/documents/upload",
                    files={"file": ("ai_overview.pdf", f, "application/pdf")},
                )
        doc_id = upload_resp.json()["id"]
        resp = client.get(f"/api/v1/documents/{doc_id}/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"

    def test_status_ready(self, client, uploaded_document):
        resp = client.get(f"/api/v1/documents/{uploaded_document.id}/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"
        assert resp.json()["total_chunks"] == 10

    def test_status_not_found(self, client):
        import uuid
        resp = client.get(f"/api/v1/documents/{uuid.uuid4()}/status")
        assert resp.status_code == 404


class TestDocumentDeletion:
    def test_delete_removes_document(self, client, uploaded_document, monkeypatch):
        monkeypatch.setattr("app.api.routes.documents.settings.UPLOAD_DIR", "/tmp")
        with patch("app.services.retrieval_service.delete_index"):
            resp = client.delete(f"/api/v1/documents/{uploaded_document.id}")
        assert resp.status_code == 204

        get_resp = client.get(f"/api/v1/documents/{uploaded_document.id}")
        assert get_resp.status_code == 404

    def test_delete_nonexistent_returns_404(self, client):
        import uuid
        resp = client.delete(f"/api/v1/documents/{uuid.uuid4()}")
        assert resp.status_code == 404
