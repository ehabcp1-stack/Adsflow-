"""AdFlow AI by TADAFQ — API entrypoint (modular monolith)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import auth, library, production, projects, workflow
from app.core.config import settings
from app.core.db import init_db
from app.core.errors import AdFlowError, adflow_error_handler, unhandled_error_handler

@asynccontextmanager
async def lifespan(application: FastAPI):
    init_db()
    # Import side effect: registers all job handlers with the queue.
    from app.services import production as _production  # noqa: F401

    if settings.STORAGE_BACKEND == "local":
        Path(settings.STORAGE_LOCAL_DIR).mkdir(parents=True, exist_ok=True)
        application.mount("/media", StaticFiles(directory=settings.STORAGE_LOCAL_DIR), name="media")
    yield


app = FastAPI(
    title="AdFlow AI API",
    description="Premium AI advertising production platform — a TADAFQ product.",
    version="1.0.0",
    docs_url="/docs",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(AdFlowError, adflow_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)

for router in (auth.router, projects.router, workflow.router, production.router, library.router):
    app.include_router(router, prefix=settings.API_PREFIX)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "parent_brand": settings.APP_BRAND_PARENT,
        "env": settings.ENV,
        "mock_providers": settings.FORCE_MOCK_PROVIDERS,
    }


@app.get("/")
def root() -> dict:
    return {"name": "AdFlow AI", "by": "TADAFQ", "docs": "/docs", "api": settings.API_PREFIX}
