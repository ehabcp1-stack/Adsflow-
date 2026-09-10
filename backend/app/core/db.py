"""Database session/engine wiring (SQLAlchemy 2.0, sync)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Generator

from sqlalchemy import DateTime, String, TypeDecorator, create_engine, func
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.core.config import settings

connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=True,
    connect_args=connect_args,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class GUID(TypeDecorator):
    """Portable UUID column: native UUID on Postgres, CHAR(36) on SQLite."""

    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: D102
        if value is None:
            return None
        return str(value)

    def process_result_value(self, value, dialect):  # noqa: D102
        if value is None:
            return None
        return str(value)


def new_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables when running without Alembic (dev/SQLite convenience)."""
    from app import models  # noqa: F401  (ensures model registration)

    Base.metadata.create_all(bind=engine)
