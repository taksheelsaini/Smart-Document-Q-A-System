"""Tests for conversation and Q&A endpoints."""

import uuid
from unittest.mock import patch


class TestConversationCreate:
    def test_create_conversation_for_ready_document(self, client, uploaded_document):
        resp = client.post(
            "/api/v1/conversations",
            json={"document_id": str(uploaded_document.id), "title": "Test Chat"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["document_id"] == str(uploaded_document.id)
        assert data["title"] == "Test Chat"
        assert data["messages"] == []

    def test_create_conversation_for_nonexistent_document(self, client):
        resp = client.post(
            "/api/v1/conversations",
            json={"document_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 404

    def test_create_conversation_for_pending_document(
        self, client, db, tmp_path, monkeypatch
    ):
        """Documents not in READY state must be rejected with 409."""
        from pathlib import Path
        from unittest.mock import patch as mp

        monkeypatch.setattr("app.api.routes.documents.settings.UPLOAD_DIR", str(tmp_path))
        sample = Path(__file__).parent.parent / "sample_docs" / "ai_overview.pdf"

        with mp("app.tasks.process_document.process_document.delay"):
            with open(sample, "rb") as f:
                upload_resp = client.post(
                    "/api/v1/documents/upload",
                    files={"file": ("ai_overview.pdf", f, "application/pdf")},
                )
        doc_id = upload_resp.json()["id"]

        resp = client.post(
            "/api/v1/conversations",
            json={"document_id": doc_id},
        )
        assert resp.status_code == 409


class TestConversationListing:
    def test_list_empty(self, client):
        resp = client.get("/api/v1/conversations")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_list_after_create(self, client, uploaded_document):
        client.post(
            "/api/v1/conversations",
            json={"document_id": str(uploaded_document.id)},
        )
        resp = client.get("/api/v1/conversations")
        assert resp.json()["total"] == 1


class TestConversationGet:
    def test_get_conversation(self, client, uploaded_document):
        create_resp = client.post(
            "/api/v1/conversations",
            json={"document_id": str(uploaded_document.id)},
        )
        conv_id = create_resp.json()["id"]
        resp = client.get(f"/api/v1/conversations/{conv_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == conv_id

    def test_get_nonexistent_conversation(self, client):
        resp = client.get(f"/api/v1/conversations/{uuid.uuid4()}")
        assert resp.status_code == 404


class TestAskQuestion:
    def _create_conversation(self, client, uploaded_document) -> str:
        resp = client.post(
            "/api/v1/conversations",
            json={"document_id": str(uploaded_document.id)},
        )
        return resp.json()["id"]

    def test_ask_returns_answer(self, client, uploaded_document):
        conv_id = self._create_conversation(client, uploaded_document)

        mock_chunks = [
            {"chunk_index": 0, "content": "AI was coined in 1956 at Dartmouth.", "relevance_score": 0.85},
        ]

        with patch("app.api.routes.conversations.search_index", return_value=mock_chunks):
            with patch(
                "app.api.routes.conversations.get_answer",
                return_value="AI was coined in 1956.",
            ):
                resp = client.post(
                    f"/api/v1/conversations/{conv_id}/ask",
                    json={"question": "When was AI coined?"},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["answer"] == "AI was coined in 1956."
        assert len(data["sources"]) == 1
        assert data["sources"][0]["relevance_score"] == 0.85

    def test_ask_persists_messages_to_history(self, client, uploaded_document):
        """After asking, the conversation should have 2 messages (user + assistant)."""
        conv_id = self._create_conversation(client, uploaded_document)

        with patch("app.api.routes.conversations.search_index", return_value=[]):
            with patch(
                "app.api.routes.conversations.get_answer",
                return_value="I could not find relevant information in the document.",
            ):
                client.post(
                    f"/api/v1/conversations/{conv_id}/ask",
                    json={"question": "What is the capital of Mars?"},
                )

        history_resp = client.get(f"/api/v1/conversations/{conv_id}")
        messages = history_resp.json()["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"

    def test_ask_no_context_still_returns_answer(self, client, uploaded_document):
        """
        When no chunks pass the threshold, the LLM should still be called
        (with empty context) and return a graceful refusal — not a 500 error.
        """
        conv_id = self._create_conversation(client, uploaded_document)

        with patch("app.api.routes.conversations.search_index", return_value=[]):
            with patch(
                "app.api.routes.conversations.get_answer",
                return_value="I could not find relevant information in the document to answer this question.",
            ):
                resp = client.post(
                    f"/api/v1/conversations/{conv_id}/ask",
                    json={"question": "What is 2+2?"},
                )

        assert resp.status_code == 200
        assert "could not find" in resp.json()["answer"].lower()

    def test_ask_empty_question_returns_400(self, client, uploaded_document):
        conv_id = self._create_conversation(client, uploaded_document)
        resp = client.post(
            f"/api/v1/conversations/{conv_id}/ask",
            json={"question": "   "},
        )
        assert resp.status_code == 400

    def test_ask_openai_down_returns_503(self, client, uploaded_document):
        from openai import APIError

        conv_id = self._create_conversation(client, uploaded_document)

        with patch("app.api.routes.conversations.search_index", return_value=[]):
            with patch(
                "app.api.routes.conversations.get_answer",
                side_effect=APIError("Service unavailable", request=None, body=None),
            ):
                resp = client.post(
                    f"/api/v1/conversations/{conv_id}/ask",
                    json={"question": "What is AI?"},
                )

        assert resp.status_code == 503
        assert "temporarily unavailable" in resp.json()["detail"].lower()

    def test_ask_nonexistent_conversation_returns_404(self, client):
        resp = client.post(
            f"/api/v1/conversations/{uuid.uuid4()}/ask",
            json={"question": "Hello?"},
        )
        assert resp.status_code == 404
