"""Structured logging.

Production logs are read by a machine first and a human second, so every line
is JSON with the identifiers that make an incident traceable: project, job,
scene, provider, operation, duration, error code.

The one rule that matters more than format: **a credential must never reach a
log line.** Provider keys arrive in headers, URLs and error payloads, so the
formatter redacts them on the way out rather than trusting every call site to
remember.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import uuid
from contextvars import ContextVar
from typing import Any, Dict, Optional

from app.core.config import settings

#: Follows one request (or one job) through every log line it produces.
request_id_var: ContextVar[str] = ContextVar("request_id", default="")
job_id_var: ContextVar[str] = ContextVar("job_id", default="")
project_id_var: ContextVar[str] = ContextVar("project_id", default="")

#: Settings whose values are secrets. Their values are scrubbed from any log.
SECRET_SETTINGS = (
    "SECRET_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "ELEVENLABS_API_KEY",
    "RUNWAY_API_KEY", "VEO_API_KEY", "SEEDANCE_API_KEY", "MUSIC_API_KEY",
    "S3_ACCESS_KEY", "S3_SECRET_KEY", "DEV_USER_PASSWORD", "WEBHOOK_SECRET",
)

#: Patterns that look like credentials wherever they appear.
_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*)(bearer\s+)?\S+"),
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|auth[_-]?token|bearer[_-]?token|token"
        r"|secret|password|passwd|pwd)\b(\s*[:=]\s*)(\"?)([^\s\",}]+)"
    ),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}\b"),
    re.compile(r"(?i)([?&](?:key|api_key|token|signature)=)[^&\s]+"),
)

REDACTED = "***redacted***"


def redact(text: str) -> str:
    """Remove anything that looks like a credential from a string."""
    if not text:
        return text
    result = str(text)
    for name in SECRET_SETTINGS:
        value = getattr(settings, name, None)
        if value and isinstance(value, str) and len(value) >= 6:
            result = result.replace(value, REDACTED)
    result = _PATTERNS[0].sub(r"\1" + REDACTED, result)
    # A usage counter like "tokens: 1500" is not a credential — only redact a
    # value that actually looks like one (long, and not a plain number).
    def _mask_pair(match: "re.Match[str]") -> str:
        value = match.group(4)
        if value.isdigit() or len(value) < 8:
            return match.group(0)
        return f"{match.group(1)}{match.group(2)}{match.group(3)}{REDACTED}"

    result = _PATTERNS[1].sub(_mask_pair, result)
    result = _PATTERNS[2].sub(REDACTED, result)
    result = _PATTERNS[3].sub(r"\1" + REDACTED, result)
    return result


#: Attributes LogRecord always carries — everything else is ours.
_STANDARD = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "module", "msecs", "message", "msg", "name",
    "pathname", "process", "processName", "relativeCreated", "stack_info",
    "thread", "threadName", "taskName",
}


class JsonFormatter(logging.Formatter):
    """One JSON object per line, with the request/job context attached."""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
                  + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        for key, var in (("request_id", request_id_var), ("job_id", job_id_var),
                         ("project_id", project_id_var)):
            value = var.get()
            if value:
                payload[key] = value
        for key, value in record.__dict__.items():
            if key not in _STANDARD and not key.startswith("_"):
                payload[key] = redact(value) if isinstance(value, str) else value
        if record.exc_info:
            payload["error_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            payload["traceback"] = redact(self.formatException(record.exc_info))[-4000:]
        return json.dumps(payload, ensure_ascii=False, default=str)


class HumanFormatter(logging.Formatter):
    """Readable during development; still redacted."""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        return redact(base)


def configure_logging(level: Optional[str] = None, json_output: Optional[bool] = None) -> None:
    """Install the formatter once, at startup."""
    resolved_level = (level or os.getenv("LOG_LEVEL")
                      or ("DEBUG" if settings.DEBUG else "INFO")).upper()
    use_json = json_output if json_output is not None else (
        os.getenv("LOG_FORMAT", "json" if settings.ENV == "production" else "human") == "json"
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter() if use_json
        else HumanFormatter("%(asctime)s %(levelname)-7s %(name)s — %(message)s", "%H:%M:%S")
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(resolved_level)
    # Uvicorn installs its own handlers; route them through ours so one process
    # never emits two log formats.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
    logging.getLogger("httpx").setLevel("WARNING")
    logging.getLogger("httpcore").setLevel("WARNING")


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


class LogContext:
    """Bind identifiers for the duration of a block (request, job, render)."""

    def __init__(self, *, request_id: Optional[str] = None, job_id: Optional[str] = None,
                 project_id: Optional[str] = None):
        self._values = {"request_id": request_id, "job_id": job_id, "project_id": project_id}
        self._tokens: Dict[str, Any] = {}

    def __enter__(self) -> "LogContext":
        for key, var in (("request_id", request_id_var), ("job_id", job_id_var),
                         ("project_id", project_id_var)):
            value = self._values.get(key)
            if value:
                self._tokens[key] = var.set(value)
        return self

    def __exit__(self, *exc: Any) -> None:
        for key, var in (("request_id", request_id_var), ("job_id", job_id_var),
                         ("project_id", project_id_var)):
            token = self._tokens.get(key)
            if token is not None:
                var.reset(token)
