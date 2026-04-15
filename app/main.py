# Copyright © Taksheel Saini. All rights reserved. | GitHub: https://github.com/taksheelsaini | LinkedIn: https://www.linkedin.com/in/taksheelsaini/# ==============================================================================
# Copyright © Taksheel Saini. All rights reserved.
# Author: Taksheel Saini
# GitHub: https://github.com/taksheelsaini
# LinkedIn: https://www.linkedin.com/in/taksheelsaini/
# ==============================================================================

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import documents, conversations
from app.core.config import settings
from app.core.database import engine
from app.models import *  # noqa: F401, F403 — ensures all models register with Base

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup / shutdown hooks."""
    import os
    from pathlib import Path

    for directory in [settings.UPLOAD_DIR, settings.INDEX_DIR]:
        Path(directory).mkdir(parents=True, exist_ok=True)
    logger.info("Storage directories verified: %s, %s", settings.UPLOAD_DIR, settings.INDEX_DIR)

    yield  # Application runs here

    logger.info("Application shutting down.")


app = FastAPI(
    title="DocQA — Smart Document Q&A API",
    description=(
        "Upload PDF or DOCX documents and ask natural-language questions answered "
        "from the document content using semantic search + LLM.\n\n"
        "**Workflow:**\n"
        "1. `POST /documents/upload` — upload a document\n"
        "2. `GET /documents/{id}/status` — wait until status is `ready`\n"
        "3. `POST /conversations` — open a conversation for the document\n"
        "4. `POST /conversations/{id}/ask` — ask questions (supports follow-ups)\n"
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# ── Middleware ──────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s — %d (%.1f ms)",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


# ── Global exception handlers ───────────────────────────────────────────────

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception on %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected internal error occurred. Please try again later."},
    )


# ── Routers ─────────────────────────────────────────────────────────────────

app.include_router(documents.router, prefix="/api/v1")
app.include_router(conversations.router, prefix="/api/v1")


# ── Health & root ────────────────────────────────────────────────────────────

@app.get("/", tags=["Health"], summary="Root — confirms the API is reachable")
def root():
    return {"service": settings.APP_NAME, "status": "ok", "version": "1.0.0"}


@app.get("/health", tags=["Health"], summary="Liveness probe")
def health():
    return {"status": "ok"}


@app.get("/health/ready", tags=["Health"], summary="Readiness probe — checks DB connection")
def readiness():
    try:
        with engine.connect() as conn:
            conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        return {"status": "ready"}
    except Exception as exc:
        logger.warning("Readiness check failed: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready", "detail": str(exc)},
        )
