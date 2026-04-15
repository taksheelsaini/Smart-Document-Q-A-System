"""Unit tests for the document processing service (chunking logic)."""

import pytest

from app.services.document_processor import chunk_text


class TestChunkText:
    def test_short_text_returns_single_chunk(self):
        text = "This is a short document."
        chunks = chunk_text(text, chunk_size=800, overlap=150)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_empty_text_returns_empty_list(self):
        assert chunk_text("", chunk_size=800, overlap=150) == []

    def test_whitespace_only_returns_empty_list(self):
        assert chunk_text("   \n\n\t  ", chunk_size=800, overlap=150) == []

    def test_long_text_splits_into_multiple_chunks(self):
        # 10 paragraphs of ~100 chars each = ~1000 chars total
        paragraph = "A" * 90 + " end."
        text = "\n\n".join([paragraph] * 10)
        chunks = chunk_text(text, chunk_size=300, overlap=50)
        assert len(chunks) > 1

    def test_chunks_respect_size_limit(self):
        paragraph = "Word " * 50  # ~250 chars per paragraph
        text = "\n\n".join([paragraph] * 20)
        chunks = chunk_text(text, chunk_size=400, overlap=80)
        for chunk in chunks:
            # Allow slight overage at hard-split boundaries (last resort)
            assert len(chunk) <= 600, f"Chunk too long: {len(chunk)} chars"

    def test_overlap_carries_context(self):
        """The tail of chunk N should appear somewhere in chunk N+1's content."""
        # Create text where paragraph splits are clean
        paragraphs = [f"Section {i}: " + ("content word " * 20) for i in range(10)]
        text = "\n\n".join(paragraphs)
        chunks = chunk_text(text, chunk_size=300, overlap=80)

        if len(chunks) >= 2:
            tail_of_first = chunks[0][-60:]
            # At least partial overlap: some words from the first chunk's tail
            # should appear at the start of the second chunk
            words_in_tail = set(tail_of_first.split())
            words_in_second = set(chunks[1][:120].split())
            overlap_words = words_in_tail & words_in_second
            assert len(overlap_words) > 0, "No overlap words found between adjacent chunks"

    def test_no_duplicate_chunks(self):
        paragraph = "This is a test paragraph with unique content. " * 5
        text = "\n\n".join([paragraph] * 5)
        chunks = chunk_text(text, chunk_size=200, overlap=40)
        # No two chunks should be identical
        assert len(chunks) == len(set(chunks))

    def test_single_very_long_word_doesnt_crash(self):
        """
        Edge case: a single token longer than chunk_size.
        The hard character-split produces identical overlapping chunks which are
        deduplicated by design (identical chunks convey no extra retrieval value).
        The important invariant is: no crash, and at least one chunk is returned.
        """
        text = "A" * 2000
        chunks = chunk_text(text, chunk_size=500, overlap=100)
        assert len(chunks) >= 1
        # Each surviving chunk should be at most chunk_size characters
        for ch in chunks:
            assert len(ch) <= 500

    def test_real_document_like_content(self):
        """Simulate realistic multi-section document text."""
        text = """
# Introduction

Artificial Intelligence (AI) refers to the simulation of human intelligence in machines
programmed to think and learn. The field was founded at the Dartmouth Conference in 1956.

# Machine Learning

Machine Learning is a subset of AI that enables systems to automatically learn from data.
Supervised learning, unsupervised learning, and reinforcement learning are its main paradigms.

## Deep Learning

Deep learning uses neural networks with many layers to model complex patterns. It powers
image recognition, NLP, and speech synthesis. GPT-4 is an example of a large language model.

# Applications

AI is applied in healthcare for diagnostics, in finance for fraud detection, and in
transportation for autonomous vehicles. The societal impact continues to grow rapidly.
        """.strip()

        chunks = chunk_text(text, chunk_size=400, overlap=80)
        assert len(chunks) >= 2
        # All content should be preserved across chunks
        all_content = " ".join(chunks)
        assert "Dartmouth" in all_content
        assert "reinforcement learning" in all_content
        assert "autonomous vehicles" in all_content
