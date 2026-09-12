"""Database session/engine wiring (SQLAlchemy 2.0, sync)."""
from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone
from typing import Any, Generator

from sqlalchemy import DateTime, String, TypeDecorator, create_engine, func
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.core.config import settings

connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}


def _json_safe(value: Any) -> Any:
    """Coerce values JSON cannot represent, before they reach a JSON column.

    Python happily carries `inf` and `nan`; `json.dumps` happily writes them as
    the non-standard `Infinity` / `NaN` literals; SQLite happily stores the
    result — and Postgres rejects the insert. The measurement that produced one
    is usually correct (the true peak of digital silence really is -inf), so the
    failure lands far from its cause: a render that worked all through local
    development dies at the save step the first time it runs on Postgres.

    This is the last line of defence. Call sites should still clamp to a
    meaningful value; `None` here means "not representable", not "zero".
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _dumps(value: Any) -> str:
    return json.dumps(_json_safe(value), ensure_ascii=False)


engine = create_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=True,
    connect_args=connect_args,
    json_serializer=_dumps,
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
