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
    ANTHROPIC_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    ELEVENLABS_API_KEY: Optional[str] = None
    RUNWAY_API_KEY: Optional[str] = None
    VEO_API_KEY: Optional[str] = None
    SEEDANCE_API_KEY: Optional[str] = None
    MUSIC_API_KEY: Optional[str] = None

    FORCE_MOCK_PROVIDERS: bool = True

    # Hero-frame-first: an AI-video scene generates a cheap still and waits for
    # a human to approve it before the expensive video call, and the approved
    # still is what the video is conditioned on. Turning this off restores
    # blind text-to-video, which costs roughly ten times more per rejected
    # take — it exists for unattended batch runs, not as a default.
    REQUIRE_KEYFRAME_APPROVAL: bool = True

    # --- Provider HTTP behaviour (app/providers/http.py) ------------------
    PROVIDER_TIMEOUT_SEC: float = 120.0
    PROVIDER_MAX_RETRIES: int = 2

    #: A structured-text completion is one request/response, not a media render,
    #: so it fails fast. 120s (PROVIDER_TIMEOUT_SEC) is a media-job timeout and
    #: far too patient for this.
    LLM_TIMEOUT_SEC: float = 60.0

    #: Wall-clock budget for one `complete_json`, retries and the repair attempt
    #: included. Without it the two retry layers MULTIPLY: 2 repair attempts x
    #: 3 HTTP attempts x 120s came to twelve minutes of silence, and nobody
    #: chose twelve minutes — it fell out of two reasonable-looking numbers.
    #: Measured live at 212s and still going, with the database answering in
    #: 79ms, so the model call was the whole of it.
    LLM_TOTAL_BUDGET_SEC: float = 150.0

    #: Object-storage fetches. botocore defaults to 60s/60s with five attempts,
    #: which is five minutes per object and unbounded across a batch.
    S3_CONNECT_TIMEOUT_SEC: float = 10.0
    S3_READ_TIMEOUT_SEC: float = 30.0
    S3_MAX_ATTEMPTS: int = 3

    #: Whole-batch ceiling for measuring a project's assets. Past it the
    #: remaining assets are reported honestly as not measured rather than
    #: holding the stage open indefinitely.
    ASSET_ANALYSIS_BUDGET_SEC: float = 120.0

    #: How long a job may claim to be RUNNING before it is treated as dead.
    #: Above the provider HTTP ceiling (3 attempts x PROVIDER_TIMEOUT_SEC plus
    #: backoff, ~6 minutes) so a slow-but-alive job is never reaped, and well
    #: under the patience of someone watching a spinner.
    JOB_STALE_AFTER_SEC: float = 900.0
    # Async video jobs (submit -> poll -> fetch) — bounds the poll loop so a
    # stuck vendor job can never hang a background worker forever.
    PROVIDER_POLL_TIMEOUT_SEC: float = 600.0
    PROVIDER_POLL_INTERVAL_SEC: float = 5.0

    # --- Provider model IDs (app/providers/catalog.py) ---------------------
    # Every one of these overrides a seeded id in the catalog. The catalog
    # records, per model, the vendor doc it was read from and the date — see
    # `ModelSpec.docs_url` / `verified_at`. A spec with no `verified_at` has
    # never been confirmed; set its override here from the vendor's own docs
    # before enabling that adapter. Vendors rename and retire models faster
    # than this file gets edited, so re-check before flipping
    # FORCE_MOCK_PROVIDERS off.
    OPENAI_LLM_MODEL: Optional[str] = None
    ANTHROPIC_LLM_MODEL: Optional[str] = None
    GEMINI_LLM_MODEL: Optional[str] = None
    OPENAI_IMAGE_MODEL: Optional[str] = None
    GEMINI_IMAGE_MODEL: Optional[str] = None
    # Veo ships three price tiers behind one key, so each tier gets its own
    # override — otherwise one variable would rename all three at once.
    VEO_VIDEO_MODEL: Optional[str] = None
    VEO_VIDEO_MODEL_ECONOMY: Optional[str] = None
    VEO_VIDEO_MODEL_PREMIUM: Optional[str] = None
    RUNWAY_VIDEO_MODEL: Optional[str] = None
    SEEDANCE_VIDEO_MODEL: Optional[str] = None
    ELEVENLABS_VOICE_MODEL: Optional[str] = None
    MUSIC_MODEL: Optional[str] = None

    # --- Provider base URLs (app/providers/http.py adapters) ---------------
    # Same caveat: unverified from this environment. Override per-operator.
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    ANTHROPIC_BASE_URL: str = "https://api.anthropic.com/v1"
    GEMINI_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta"
    ELEVENLABS_BASE_URL: str = "https://api.elevenlabs.io/v1"
    RUNWAY_BASE_URL: str = "https://api.dev.runwayml.com/v1"
    VEO_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta"
    SEEDANCE_BASE_URL: str = "https://api.bytedance.com/v1"
    MUSIC_BASE_URL: str = "https://api.example-music-provider.invalid/v1"

    # --- Cost / budget ---------------------------------------------------
    DEFAULT_PROJECT_BUDGET_USD: float = 12.0
    MONTHLY_BUDGET_TARGET_USD: float = 50.0
    #: A hard ceiling across every project in the organisation for the calendar
    #: month. The per-project budget stops one runaway render; this stops a
    #: month of small ones adding up to a bill nobody chose. 0 disables it.
    MONTHLY_BUDGET_HARD_CAP_USD: float = 60.0
    #: Warn at this fraction of the cap, while there is still time to react.
    MONTHLY_BUDGET_ALERT_RATIO: float = 0.8
    REGENERATION_RESERVE_RATIO: float = 0.20
    QC_APPROVE_THRESHOLD: float = 90.0
    QC_REVIEW_THRESHOLD: float = 85.0
    SCENE_QUALITY_THRESHOLD: float = 90.0
    DEFAULT_QUALITY_LEVEL: str = "smart_premium"
    # Hard ceiling on what a single "test this provider connection" action may
    # spend — see providers/pricing.guard_integration_spend(). No real keys
    # exist in dev, but this stays enforced everywhere so it is never an
    # afterthought in production.
    INTEGRATION_TEST_BUDGET_USD: float = 1.0

    # --- Webhooks --------------------------------------------------------
    # Fail-closed: without a secret the callback endpoint rejects everything,
    # because a webhook that trusts any caller is worse than no webhook.
    WEBHOOK_SECRET: Optional[str] = None
    VEO_WEBHOOK_SECRET: Optional[str] = None
    RUNWAY_WEBHOOK_SECRET: Optional[str] = None
    SEEDANCE_WEBHOOK_SECRET: Optional[str] = None

    # --- Uploads ---------------------------------------------------------
    MAX_UPLOAD_MB: int = 400

    # --- Logging ---------------------------------------------------------
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "human"  # "json" in production

    # --- Media -----------------------------------------------------------
    FFMPEG_BIN: str = "ffmpeg"
    FFPROBE_BIN: str = "ffprobe"
    ENABLE_LOCAL_RENDER: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
