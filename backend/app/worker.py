"""Celery worker (optional).

Default V1 runs JOB_BACKEND=inline — a thread pool inside the API process,
which needs no Redis and is the most reliable local setup. Set
JOB_BACKEND=celery plus REDIS_URL to scale out:

    celery -A app.worker.celery_app worker --loglevel=info
"""
from __future__ import annotations

from celery import Celery

from app.core.config import settings
from app.core.db import SessionLocal

celery_app = Celery("adflow", broker=settings.REDIS_URL, backend=settings.REDIS_URL)
celery_app.conf.update(task_serializer="json", result_serializer="json", accept_content=["json"], timezone="UTC")


@celery_app.task(name="adflow.run_job")
def run_job_task(job_id: str) -> str:  # pragma: no cover - requires a broker
    from app.services import production as _production  # noqa: F401  (registers handlers)
    from app.services.jobs import execute_job

    db = SessionLocal()
    try:
        execute_job(db, job_id)
        return job_id
    finally:
        db.close()
