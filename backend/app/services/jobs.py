"""Job queue abstraction.

Long-running generation never blocks an HTTP request.

Backends:
    inline  (default) — a background thread pool inside the API process.
                        Zero infrastructure; perfect for local development.
    celery            — dispatch to Celery workers over Redis (see worker.py).

Both share the same GenerationJob rows, so the UI polls one endpoint either way.
"""
from __future__ import annotations

import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal, utcnow
from app.core.enums import JobStatus
from app.models import GenerationJob, Project

JobHandler = Callable[[Session, GenerationJob], Dict[str, Any]]
_HANDLERS: Dict[str, JobHandler] = {}
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="adflow-job")
_lock = threading.Lock()


def register_handler(job_type: str) -> Callable[[JobHandler], JobHandler]:
    def decorator(func: JobHandler) -> JobHandler:
        _HANDLERS[job_type] = func
        return func

    return decorator


def create_job(
    db: Session,
    *,
    project: Project,
    job_type: str,
    payload: Optional[Dict[str, Any]] = None,
    scene_id: Optional[str] = None,
    estimated_cost_usd: float = 0.0,
    max_attempts: int = 3,
) -> GenerationJob:
    job = GenerationJob(
        project_id=project.id,
        scene_id=scene_id,
        job_type=job_type,
        status=JobStatus.QUEUED.value,
        payload=payload or {},
        estimated_cost_usd=estimated_cost_usd,
        max_attempts=max_attempts,
    )
    db.add(job)
    db.flush()
    return job


def dispatch(job_id: str) -> None:
    """Hand the job to the configured backend."""
    if settings.JOB_BACKEND == "celery":  # pragma: no cover - requires broker
        from app.worker import run_job_task

        run_job_task.delay(job_id)
        return
    _executor.submit(_run_inline, job_id)


def _run_inline(job_id: str) -> None:
    db = SessionLocal()
    try:
        execute_job(db, job_id)
    except Exception:  # pragma: no cover - defensive
        traceback.print_exc()
    finally:
        db.close()


def execute_job(db: Session, job_id: str) -> None:
    job = db.get(GenerationJob, job_id)
    if not job or job.status in (JobStatus.COMPLETED.value, JobStatus.CANCELLED.value):
        return
    handler = _HANDLERS.get(job.job_type)
    if handler is None:
        job.status = JobStatus.FAILED.value
        job.error_message = f"No handler registered for job type '{job.job_type}'"
        db.commit()
        return

    job.status = JobStatus.RUNNING.value
    job.started_at = utcnow()
    job.progress = 0.05
    db.commit()

    try:
        result = handler(db, job)
        job.result = result or {}
        job.status = JobStatus.COMPLETED.value
        job.progress = 1.0
        job.progress_label = "completed"
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI as a friendly state
        job.status = JobStatus.FAILED.value
        job.error_message = str(exc)[:500]
        job.progress_label = "failed"
    finally:
        job.finished_at = utcnow()
        db.commit()


def set_progress(db: Session, job: GenerationJob, value: float, label: str) -> None:
    job.progress = round(min(max(value, 0.0), 1.0), 3)
    job.progress_label = label
    db.commit()


def job_payload(job: GenerationJob) -> Dict[str, Any]:
    return {
        "id": job.id,
        "project_id": job.project_id,
        "scene_id": job.scene_id,
        "job_type": job.job_type,
        "status": job.status,
        "progress": job.progress,
        "progress_label": job.progress_label,
        "attempt": job.attempt,
        "max_attempts": job.max_attempts,
        "estimated_cost_usd": job.estimated_cost_usd,
        "actual_cost_usd": job.actual_cost_usd,
        "error_message": job.error_message,
        "result": job.result,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }
