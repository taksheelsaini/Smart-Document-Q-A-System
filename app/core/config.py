# Copyright © Taksheel Saini. All rights reserved. | GitHub: https://github.com/taksheelsaini | LinkedIn: https://www.linkedin.com/in/taksheelsaini/from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    APP_NAME: str = "DocQA"
    DEBUG: bool = False
    MAX_UPLOAD_SIZE_MB: int = 50

    # Database
    DATABASE_URL: str = "postgresql://docqa_user:docqa_pass@localhost:5432/docqa"

    # Redis / Celery
    REDIS_URL: str = "redis://localhost:6379/0"

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_BASE_URL: str | None = None
    OPENAI_HTTP_REFERER: str | None = None
    OPENAI_APP_TITLE: str | None = None
    OPENAI_MAX_TOKENS: int = 1024
    OPENAI_TEMPERATURE: float = 0.1

    # Storage paths (overridden to /data/* inside Docker)
    UPLOAD_DIR: str = "/data/uploads"
    INDEX_DIR: str = "/data/indices"

    # Chunking
    CHUNK_SIZE: int = 800
    CHUNK_OVERLAP: int = 150

    # Retrieval
    RETRIEVAL_TOP_K: int = 5
    RETRIEVAL_SCORE_THRESHOLD: float = 0.12

    # Conversation
    MAX_HISTORY_TURNS: int = 5

    # Embedding
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_DIM: int = 384


settings = Settings()
