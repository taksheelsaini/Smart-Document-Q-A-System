"""Unit tests for LLM service prompt construction."""

from app.services.llm_service import build_messages, SYSTEM_PROMPT


class TestBuildMessages:
    def test_system_message_always_first(self):
        messages = build_messages([], [], "What is AI?")
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == SYSTEM_PROMPT

    def test_question_appended_with_context(self):
        chunks = [{"content": "AI was founded in 1956.", "chunk_index": 0, "relevance_score": 0.9}]
        messages = build_messages(chunks, [], "When was AI founded?")
        user_msg = messages[-1]
        assert user_msg["role"] == "user"
        assert "1956" in user_msg["content"]
        assert "When was AI founded?" in user_msg["content"]
        assert "Excerpt 1" in user_msg["content"]

    def test_no_context_inserts_notice(self):
        messages = build_messages([], [], "Random question")
        user_msg = messages[-1]
        assert "No relevant excerpts" in user_msg["content"]

    def test_history_injected_between_system_and_current(self):
        history = [
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": "First answer"},
        ]
        messages = build_messages([], history, "Follow-up question")
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "First question"
        assert messages[2]["role"] == "assistant"
        assert messages[-1]["content"].endswith("Follow-up question")

    def test_history_trimmed_to_max_turns(self):
        history = []
        for i in range(10):
            history.append({"role": "user", "content": f"Q{i}"})
            history.append({"role": "assistant", "content": f"A{i}"})

        messages = build_messages([], history, "New question")
        # system + MAX_HISTORY_TURNS*2 + current user = 1 + 10 + 1 = 12
        from app.core.config import settings
        max_history_messages = settings.MAX_HISTORY_TURNS * 2
        assert len(messages) == 1 + max_history_messages + 1

    def test_multiple_context_chunks_numbered(self):
        chunks = [
            {"content": "Chunk A text", "chunk_index": 0, "relevance_score": 0.9},
            {"content": "Chunk B text", "chunk_index": 1, "relevance_score": 0.8},
            {"content": "Chunk C text", "chunk_index": 2, "relevance_score": 0.7},
        ]
        messages = build_messages(chunks, [], "Question?")
        user_content = messages[-1]["content"]
        assert "Excerpt 1" in user_content
        assert "Excerpt 2" in user_content
        assert "Excerpt 3" in user_content
        assert "Chunk A text" in user_content
        assert "Chunk C text" in user_content
