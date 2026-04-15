"""Security-focused input validation tests."""

from pathlib import Path
from unittest.mock import patch


SAMPLE_PDF = Path(__file__).parent.parent / "sample_docs" / "ai_overview.pdf"


class TestUploadSecurity:
    def test_oversized_upload_returns_413(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr("app.api.routes.documents.settings.UPLOAD_DIR", str(tmp_path))
        monkeypatch.setattr("app.api.routes.documents.settings.MAX_UPLOAD_SIZE_MB", 1)

        large_payload = b"x" * (1024 * 1024 + 1)
        resp = client.post(
            "/api/v1/documents/upload",
            files={"file": ("large.pdf", large_payload, "application/pdf")},
        )
        assert resp.status_code == 413

    def test_path_traversal_filename_is_not_used_for_storage(
        self, client, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("app.api.routes.documents.settings.UPLOAD_DIR", str(tmp_path))

        with patch("app.tasks.process_document.process_document.delay"):
            with open(SAMPLE_PDF, "rb") as f:
                resp = client.post(
                    "/api/v1/documents/upload",
                    files={"file": ("../../etc/passwd.pdf", f, "application/pdf")},
                )

        assert resp.status_code == 202
        data = resp.json()
        assert data["original_filename"] == "passwd.pdf"

        saved_files = list(tmp_path.iterdir())
        assert len(saved_files) == 1
        assert saved_files[0].suffix == ".pdf"
        assert ".." not in saved_files[0].name


class TestAskSecurity:
    def test_ask_overlong_question_returns_422(self, client, uploaded_document):
        create = client.post(
            "/api/v1/conversations",
            json={"document_id": str(uploaded_document.id)},
        )
        conv_id = create.json()["id"]

        too_long_question = "a" * 4001
        resp = client.post(
            f"/api/v1/conversations/{conv_id}/ask",
            json={"question": too_long_question},
        )

        assert resp.status_code == 422
