"""AdFlow AI — application configuration.

Never hard-code secrets. Everything comes from the environment (.env).
See .env.example at the repository root.
"""
from __future__ import annotations

from functools import lru_cache
from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    # --- App -------------------------------------------------------------
    APP_NAME: str = "AdFlow AI"
    APP_BRAND_PARENT: str = "TADAFQ"
    ENV: str = "development"
    DEBUG: bool = True
    API_PREFIX: str = "/api/v1"

    # --- Security --------------------------------------------------------
    SECRET_KEY: str = "dev-only-insecure-secret-change-me"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7
    ALLOW_DEV_LOGIN: bool = True
    DEV_USER_EMAIL: str = "demo@tadafq.com"
    DEV_USER_PASSWORD: str = "demo1234"

    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
    ]

    # --- Database --------------------------------------------------------
    # Defaults to a local SQLite file so the whole product runs with zero
    # infrastructure. Set DATABASE_URL to Postgres for docker/production.
    DATABASE_URL: str = "sqlite:///./adflow.db"

    # --- Queue / cache ---------------------------------------------------
    REDIS_URL: str = "redis://localhost:6379/0"
    # "inline" = in-process background worker (default, zero infra)
    # "celery" = dispatch to Celery workers over Redis
    JOB_BACKEND: str = "inline"

    # --- Storage ---------------------------------------------------------
    # "local" = ./storage directory served by the API (dev only)
    # "s3"    = any S3-compatible endpoint (MinIO, AWS, R2, ...)
    STORAGE_BACKEND: str = "local"
    STORAGE_LOCAL_DIR: str = "./storage"
    S3_ENDPOINT_URL: Optional[str] = None
    S3_BUCKET: str = "adflow"
    S3_ACCESS_KEY: Optional[str] = None
    S3_SECRET_KEY: Optional[str] = None
    S3_REGION: str = "us-east-1"
    PUBLIC_MEDIA_BASE_URL: str = "http://localhost:8000/media"

    # --- Providers -------------------------------------------------------
    # When a key is missing the corresponding Mock adapter is used and the
    # complete product remains usable. Never leak these to the browser.
    OPENAI_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    ELEVENLABS_API_KEY: Optional[str] = None
    RUNWAY_API_KEY: Optional[str] = None
    VEO_API_KEY: Optional[str] = None
    SEEDANCE_API_KEY: Optional[str] = None
    MUSIC_API_KEY: Optional[str] = None

    FORCE_MOCK_PROVIDERS: bool = True

    # --- Cost / budget ---------------------------------------------------
    DEFAULT_PROJECT_BUDGET_USD: float = 12.0
    MONTHLY_BUDGET_TARGET_USD: float = 50.0
    REGENERATION_RESERVE_RATIO: float = 0.20
    QC_APPROVE_THRESHOLD: float = 90.0
    QC_REVIEW_THRESHOLD: float = 85.0
    SCENE_QUALITY_THRESHOLD: float = 90.0
    DEFAULT_QUALITY_LEVEL: str = "smart_premium"

    # --- Media -----------------------------------------------------------
    FFMPEG_BIN: str = "ffmpeg"
    FFPROBE_BIN: str = "ffprobe"
    ENABLE_LOCAL_RENDER: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
