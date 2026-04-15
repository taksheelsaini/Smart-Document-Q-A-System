# Copyright © Taksheel Saini. All rights reserved. | GitHub: https://github.com/taksheelsaini | LinkedIn: https://www.linkedin.com/in/taksheelsaini/from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "docqa",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks.process_document"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    # Acknowledge the task only after it completes (not when dequeued).
    # This prevents task loss if a worker crashes mid-execution.
    task_acks_late=True,
    # One task at a time per worker slot — avoids memory spikes from
    # concurrent embedding model loads.
    worker_prefetch_multiplier=1,
)
