# Copyright © Taksheel Saini. All rights reserved. | GitHub: https://github.com/taksheelsaini | LinkedIn: https://www.linkedin.com/in/taksheelsaini/"""
LLM service: prompt construction and OpenAI chat completions.

Prompt engineering choices:
  - System prompt instructs the model to answer strictly from provided context
    and to say "I could not find relevant information" when context is absent.
    This hard instruction, combined with a threshold-filtered retrieval layer,
    is the primary hallucination guard.
  - Conversation history is appended before the current question so the model
    can handle follow-up references ("what did you mean by X?").
  - Context is injected fresh on every turn rather than relying on the model's
    memory of previous context blocks. This ensures each question gets the most
    relevant retrieval results regardless of how the conversation has evolved.
  - Temperature is set to 0.1 to keep answers factual and deterministic.

Retry strategy (tenacity):
  - Retries on APITimeoutError and RateLimitError with exponential back-off.
  - Other APIErrors (auth failures, invalid requests) are not retried — they
    would fail again immediately and should surface to the caller.
"""

import logging
from typing import Optional

from openai import APIError, APITimeoutError, OpenAI, RateLimitError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: Optional[OpenAI] = None

SYSTEM_PROMPT = """\
You are a precise document assistant. Your sole job is to answer questions \
using information from the document excerpts provided below each question.

Rules you must always follow:
1. Answer ONLY from the provided excerpts. Do not use outside knowledge.
2. If the answer is not present in the excerpts, respond with exactly:
   "I could not find relevant information in the document to answer this question."
3. Do not speculate, infer beyond the text, or fabricate details.
4. Be concise and accurate. Quote or paraphrase the excerpts when it adds clarity.
5. For follow-up questions, use both the excerpts and the conversation history \
to give a coherent, consistent answer.\
"""


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        default_headers: dict[str, str] = {}
        if settings.OPENAI_HTTP_REFERER:
            default_headers["HTTP-Referer"] = settings.OPENAI_HTTP_REFERER
        if settings.OPENAI_APP_TITLE:
            default_headers["X-OpenRouter-Title"] = settings.OPENAI_APP_TITLE

        client_kwargs: dict = {
            "api_key": settings.OPENAI_API_KEY,
            "timeout": 30.0,
        }
        if settings.OPENAI_BASE_URL:
            client_kwargs["base_url"] = settings.OPENAI_BASE_URL
        if default_headers:
            client_kwargs["default_headers"] = default_headers

        _client = OpenAI(**client_kwargs)
    return _client


def build_messages(
    context_chunks: list[dict],
    history: list[dict],
    question: str,
) -> list[dict]:
    """
    Construct the OpenAI messages array.

    Structure:
      [system]
      [user/assistant turns from history — up to MAX_HISTORY_TURNS pairs]
      [user: injected context + current question]

    The current question always carries fresh context so the model is never
    limited to stale excerpts from earlier turns.
    """
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Trim history to the most recent N turn-pairs (user+assistant = 2 messages)
    for msg in history[-(settings.MAX_HISTORY_TURNS * 2) :]:
        messages.append({"role": msg["role"], "content": msg["content"]})

    if context_chunks:
        context_text = "\n\n---\n\n".join(
            f"[Excerpt {i + 1}]\n{chunk['content']}"
            for i, chunk in enumerate(context_chunks)
        )
        user_content = (
            f"Relevant excerpts from the document:\n\n{context_text}"
            f"\n\n---\n\nQuestion: {question}"
        )
    else:
        # No chunks passed the relevance threshold — tell the model explicitly.
        user_content = (
            "Note: No relevant excerpts were retrieved from the document "
            f"for this question.\n\nQuestion: {question}"
        )

    messages.append({"role": "user", "content": user_content})
    return messages


@retry(
    retry=retry_if_exception_type((APITimeoutError, RateLimitError)),
    wait=wait_exponential(multiplier=1, min=2, max=15),
    stop=stop_after_attempt(3),
    reraise=True,
)
def _call_openai(messages: list[dict]) -> str:
    """Execute a single chat completion request with automatic retry on transient errors."""
    client = _get_client()
    response = client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=messages,  # type: ignore[arg-type]
        max_tokens=settings.OPENAI_MAX_TOKENS,
        temperature=settings.OPENAI_TEMPERATURE,
    )
    return response.choices[0].message.content.strip()


def get_answer(
    context_chunks: list[dict],
    history: list[dict],
    question: str,
) -> str:
    """
    Generate a grounded answer for *question* given retrieval *context_chunks*
    and the prior *history* of the conversation.

    Raises openai.APIError if the service is unavailable after all retries.
    """
    messages = build_messages(context_chunks, history, question)
    try:
        return _call_openai(messages)
    except APIError:
        logger.error("OpenAI API unavailable after retries.", exc_info=True)
        raise
