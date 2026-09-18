"""AdFlow AI by TADAFQ — API entrypoint (modular monolith)."""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import auth, library, production, projects, system, webhooks, workflow
from app.core.config import settings
from app.core.db import init_db
from app.core.errors import AdFlowError, adflow_error_handler, unhandled_error_handler
from app.core.logging import LogContext, configure_logging, new_request_id

log = logging.getLogger("adflow.api")


@asynccontextmanager
async def lifespan(application: FastAPI):
    configure_logging(settings.LOG_LEVEL, json_output=settings.LOG_FORMAT.lower() == "json")
    init_db()
    # Import side effect: registers all job handlers with the queue.
    from app.services import production as _production  # noqa: F401
    from app.services import stage_jobs as _stage_jobs  # noqa: F401

    # A job found RUNNING before this process has run anything was left behind
    # by the previous one — the inline worker pool lives inside this process,
    # so it died with it. Left alone the row says "running" forever: the screen
    # polls something that will never move, and the idempotency check hands the
    # same dead job back to every retry, so the stage can never be run again.
    from app.core.db import SessionLocal
    from app.services.jobs import reap_stale_jobs

    _boot_db = SessionLocal()
    try:
        interrupted = reap_stale_jobs(_boot_db, all_running=True)
        if interrupted:
            log.warning("marked %s job(s) failed: interrupted by a restart", interrupted)
    finally:
        _boot_db.close()

    if settings.STORAGE_BACKEND == "local":
        Path(settings.STORAGE_LOCAL_DIR).mkdir(parents=True, exist_ok=True)
        application.mount("/media", StaticFiles(directory=settings.STORAGE_LOCAL_DIR), name="media")
    log.info(
        "AdFlow AI API started",
        extra={"env": settings.ENV, "storage": settings.STORAGE_BACKEND,
               "jobs": settings.JOB_BACKEND, "mock_providers": settings.FORCE_MOCK_PROVIDERS},
    )
    yield


app = FastAPI(
    title="AdFlow AI API",
    description="Premium AI advertising production platform — a TADAFQ product.",
    version="1.0.0",
    docs_url="/docs",
    lifespan=lifespan,
)


def _cors_origins() -> list[str]:
    """Production must not accept every origin.

    An open CORS policy on an API that spends money on the user's behalf is a
    real exposure, so production uses exactly the configured list and only
    development falls back to localhost.
    """
    configured = [origin.strip() for origin in settings.CORS_ORIGINS if origin.strip()]
    if settings.ENV == "production":
        if not configured or "*" in configured:
            log.warning(
                "CORS_ORIGINS is empty or wildcard in production — refusing to allow all "
                "origins. Set it to the deployed frontend URL."
            )
            return []
        return configured
    return configured or ["http://localhost:3000"]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-Id"],
    expose_headers=["X-Request-Id"],
    max_age=600,
)


@app.middleware("http")
async def request_context(request: Request, call_next: Any):
    """Give every request an id and one structured log line."""
    request_id = request.headers.get("X-Request-Id") or new_request_id()
    started = time.perf_counter()
    with LogContext(request_id=request_id):
        try:
            response = await call_next(request)
        except Exception:  # noqa: BLE001 - handled by the exception handlers
            log.exception(
                "request failed",
                extra={"method": request.method, "path": request.url.path},
            )
            raise
        duration_ms = int((time.perf_counter() - started) * 1000)
        response.headers["X-Request-Id"] = request_id
        # Static media is noise; the API is what we care about.
        if not request.url.path.startswith("/media"):
            log.info(
                "request",
                extra={"method": request.method, "path": request.url.path,
                       "status": response.status_code, "duration_ms": duration_ms},
            )
        return response


app.add_exception_handler(AdFlowError, adflow_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)

for router in (auth.router, projects.router, workflow.router, production.router,
               library.router, system.router, webhooks.router):
    app.include_router(router, prefix=settings.API_PREFIX)


@app.get("/health")
def health() -> Dict[str, Any]:
    """Liveness: the process is up. Cheap enough for a 10-second interval."""
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "parent_brand": settings.APP_BRAND_PARENT,
        "env": settings.ENV,
        "mock_providers": settings.FORCE_MOCK_PROVIDERS,
    }


@app.get("/ready")
def ready() -> JSONResponse:
    """Readiness: can this instance actually serve work?

    Checked against the dependencies a render needs — the database, the storage
    backend, the queue and FFmpeg. A rolling deploy must not send traffic to an
    instance that would fail the first job it picks up.
    """
    from sqlalchemy import text

    from app.core.db import SessionLocal
    from app.media.ffmpeg import ffmpeg_available, ffprobe_available
    from app.services.storage import get_storage

    checks: Dict[str, Any] = {}

    try:
        session = SessionLocal()
        session.execute(text("SELECT 1"))
        session.close()
        checks["database"] = {"ok": True}
    except Exception as exc:  # noqa: BLE001
        checks["database"] = {"ok": False, "error": str(exc)[:200]}

    try:
        storage = get_storage()
        probe_key = ".readiness"
        storage.put_bytes(probe_key, b"ok", "text/plain")
        checks["storage"] = {"ok": True, "backend": settings.STORAGE_BACKEND}
    except Exception as exc:  # noqa: BLE001
        checks["storage"] = {"ok": False, "backend": settings.STORAGE_BACKEND,
                             "error": str(exc)[:200]}

    if settings.JOB_BACKEND == "celery":
        try:
            import redis  # noqa: PLC0415 - optional dependency

            redis.from_url(settings.REDIS_URL).ping()
            checks["queue"] = {"ok": True, "backend": "celery"}
        except Exception as exc:  # noqa: BLE001
            checks["queue"] = {"ok": False, "backend": "celery", "error": str(exc)[:200]}
    else:
        checks["queue"] = {"ok": True, "backend": "inline"}

    render_ready = ffmpeg_available() and ffprobe_available()
    checks["render"] = {
        "ok": render_ready or not settings.ENABLE_LOCAL_RENDER,
        "ffmpeg": ffmpeg_available(),
        "ffprobe": ffprobe_available(),
        "local_render_enabled": settings.ENABLE_LOCAL_RENDER,
    }

    ready_now = all(check.get("ok") for check in checks.values())
    return JSONResponse(
        status_code=200 if ready_now else 503,
        content={"status": "ready" if ready_now else "not_ready", "checks": checks},
    )


@app.get("/")
def root() -> Dict[str, Any]:
    return {"name": "AdFlow AI", "by": "TADAFQ", "docs": "/docs", "api": settings.API_PREFIX}
