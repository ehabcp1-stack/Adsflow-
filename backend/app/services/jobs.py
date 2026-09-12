"""Job queue abstraction.

Long-running generation never blocks an HTTP request.

Backends:
    inline  (default) — a background thread pool inside the API process.
                        Zero infrastructure; perfect for local development.
    celery            — dispatch to Celery workers over Redis (see worker.py).

Both share the same GenerationJob rows, so the UI polls one endpoint either way.
"""
from __future__ import annotations

import hashlib
import json
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


def idempotency_key(project_id: str, job_type: str, scene_id: Optional[str],
                    payload: Optional[Dict[str, Any]]) -> str:
    """Stable fingerprint of "this exact piece of work".

    Two identical requests — a double-clicked button, a retried HTTP call —
    must not become two paid provider jobs.
    """
    material = json.dumps(
        {"p": project_id, "t": job_type, "s": scene_id,
         "d": {k: v for k, v in (payload or {}).items() if k != "regeneration"}},
        sort_keys=True, ensure_ascii=False, default=str,
    )
    return hashlib.sha256(material.encode()).hexdigest()[:32]


def find_active_duplicate(db: Session, *, project_id: str, job_type: str,
                          scene_id: Optional[str],
                          payload: Optional[Dict[str, Any]]) -> Optional[GenerationJob]:
    """An in-flight job for the same work, if one exists."""
    key = idempotency_key(project_id, job_type, scene_id, payload)
    candidates = (
        db.query(GenerationJob)
        .filter(
            GenerationJob.project_id == project_id,
            GenerationJob.job_type == job_type,
            GenerationJob.status.in_(
                [JobStatus.QUEUED.value, JobStatus.RUNNING.value, JobStatus.RETRYING.value]
            ),
        )
        .all()
    )
    for job in candidates:
        if (job.payload or {}).get("_idempotency_key") == key and job.scene_id == scene_id:
            return job
    return None


def create_job(
    db: Session,
    *,
    project: Project,
    job_type: str,
    payload: Optional[Dict[str, Any]] = None,
    scene_id: Optional[str] = None,
    estimated_cost_usd: float = 0.0,
    max_attempts: int = 3,
    reuse_active: bool = True,
) -> GenerationJob:
    """Create a job, or hand back the identical one already in flight."""
    body = dict(payload or {})
    if reuse_active:
        existing = find_active_duplicate(
            db, project_id=project.id, job_type=job_type, scene_id=scene_id, payload=body
        )
        if existing is not None:
            return existing
    body["_idempotency_key"] = idempotency_key(project.id, job_type, scene_id, body)
    job = GenerationJob(
        project_id=project.id,
        scene_id=scene_id,
        job_type=job_type,
        status=JobStatus.QUEUED.value,
        payload=body,
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


def claim_job(db: Session, job_id: str) -> Optional[GenerationJob]:
    """Atomically take ownership of a queued job.

    Without this a job can run twice at once — the queue dispatches it to a
    worker while something else (the seeder, a retried request) executes it
    inline — and two FFmpeg processes write the same output file, producing a
    corrupt clip that still looks plausible. The claim is a conditional UPDATE,
    so exactly one caller wins.
    """
    claimable = (JobStatus.QUEUED.value, JobStatus.RETRYING.value)
    updated = (
        db.query(GenerationJob)
        .filter(GenerationJob.id == job_id, GenerationJob.status.in_(claimable))
        .update(
            {GenerationJob.status: JobStatus.RUNNING.value, GenerationJob.started_at: utcnow()},
            synchronize_session=False,
        )
    )
    db.commit()
    if not updated:
        return None
    db.expire_all()
    return db.get(GenerationJob, job_id)


def execute_job(db: Session, job_id: str) -> None:
    job = db.get(GenerationJob, job_id)
    if not job or job.status in (
        JobStatus.COMPLETED.value, JobStatus.CANCELLED.value, JobStatus.RUNNING.value
    ):
        return
    job = claim_job(db, job_id)
    if job is None:  # another worker got there first
        return
    handler = _HANDLERS.get(job.job_type)
    if handler is None:
        job.status = JobStatus.FAILED.value
        job.error_message = f"No handler registered for job type '{job.job_type}'"
        db.commit()
        return

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


def cancel_job(db: Session, job: GenerationJob) -> Dict[str, Any]:
    """Cancel a job, and be honest about what cancellation actually means.

    A queued job simply never starts. A job already running locally is marked
    cancelled and its result discarded. A job that has been handed to an
    external provider may already have incurred cost — we say so rather than
    implying the charge was stopped.
    """
    if job.status in (JobStatus.COMPLETED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value):
        return {"ok": False, "status": job.status,
                "message_en": "This job has already finished.",
                "message_ar": "هاي المهمة خلصت من قبل."}

    provider_side = bool((job.result or {}).get("provider_job_id"))
    was_running = job.status == JobStatus.RUNNING.value
    job.status = JobStatus.CANCELLED.value
    job.progress_label = "cancelled"
    job.finished_at = utcnow()
    db.commit()
    if provider_side:
        message_en = ("Cancelled on our side. The provider job was already submitted, "
                      "so any cost it has already incurred still stands.")
        message_ar = ("انلغت من طرفنا. الطلب كان مرسل للمزود، فأي كلفة انصرفت تبقى محسوبة.")
    elif was_running:
        message_en = "Cancelled. The work in progress was discarded."
        message_ar = "انلغت، والشغل اللي كان يشتغل انلغى."
    else:
        message_en = "Cancelled before it started. Nothing was spent."
        message_ar = "انلغت قبل ما تبدي. ما انصرف شي."
    return {"ok": True, "status": job.status, "provider_side": provider_side,
            "message_en": message_en, "message_ar": message_ar}
