"""Shared HTTP client for real provider adapters.

One place owns retry policy, error classification and — critically —
secret redaction, so no adapter can accidentally leak an Authorization
header or API key into a log line or a `ProviderResult.error` string that
reaches the UI. Adapters call `post_json` / `get_json` / `download_to_file`
and handle the raised `ProviderHttpError`; they never touch `httpx` directly.
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Redaction
# --------------------------------------------------------------------------
#: Patterns matching things that must never reach a log line or error string.
#: Each keeps its own harmless prefix (so the reader still sees "Bearer" or
#: "api_key=") and replaces only the secret portion.
_REDACT_PATTERNS = [
    re.compile(r"(Bearer\s+)[A-Za-z0-9\-._~+/]{6,}=*", re.IGNORECASE),
    re.compile(r'("?[Aa]uthorization"?\s*[:=]\s*"?)(?:Bearer\s+)?[A-Za-z0-9\-._~+/]{6,}=*'),
    re.compile(r'("?api[_-]?key"?\s*[:=]\s*"?)[A-Za-z0-9\-._~+/]{6,}', re.IGNORECASE),
    re.compile(r'("?x-api-key"?\s*[:=]\s*"?)[A-Za-z0-9\-._~+/]{6,}', re.IGNORECASE),
    re.compile(r"([?&](?:key|api[_-]?key|apikey|token|access_token)=)[^&\s\"']+", re.IGNORECASE),
]


def redact(text: str) -> str:
    """Strip anything that looks like a bearer token, api key or key= query param.

    Best-effort by design: providers occasionally echo request details (bad
    auth, malformed query strings) back in error bodies, and this is the
    single choke point that keeps that out of logs and user-facing errors.
    """
    if not text:
        return text
    out = str(text)
    for pattern in _REDACT_PATTERNS:
        out = pattern.sub(lambda m: m.group(1) + "[REDACTED]", out)
    return out


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------
class ErrorKind:
    AUTH = "AUTH"
    RATE_LIMIT = "RATE_LIMIT"
    TIMEOUT = "TIMEOUT"
    SERVER = "SERVER"
    BAD_REQUEST = "BAD_REQUEST"
    UNKNOWN = "UNKNOWN"


class ProviderHttpError(Exception):
    """Raised for any failed provider HTTP call, message pre-redacted."""

    def __init__(self, kind: str, message: str, status_code: Optional[int] = None):
        redacted = redact(message)
        super().__init__(redacted)
        self.kind = kind
        self.message = redacted
        self.status_code = status_code


def _classify(status_code: Optional[int]) -> str:
    if status_code in (401, 403):
        return ErrorKind.AUTH
    if status_code == 429:
        return ErrorKind.RATE_LIMIT
    if status_code is not None and 500 <= status_code < 600:
        return ErrorKind.SERVER
    if status_code is not None and 400 <= status_code < 500:
        return ErrorKind.BAD_REQUEST
    return ErrorKind.UNKNOWN


def _retryable(kind: str) -> bool:
    return kind in (ErrorKind.RATE_LIMIT, ErrorKind.SERVER, ErrorKind.TIMEOUT)


def _backoff_sleep(attempt: int) -> None:
    time.sleep(min(2**attempt, 10))


def _resolved(timeout: Optional[float], max_retries: Optional[int]) -> tuple[float, int]:
    return (
        timeout if timeout is not None else settings.PROVIDER_TIMEOUT_SEC,
        max_retries if max_retries is not None else settings.PROVIDER_MAX_RETRIES,
    )


def _request(
    method: str,
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    json: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: Optional[float] = None,
    max_retries: Optional[int] = None,
) -> httpx.Response:
    timeout_s, retries = _resolved(timeout, max_retries)
    last_error: Optional[str] = None
    for attempt in range(retries + 1):
        try:
            with httpx.Client(timeout=timeout_s) as client:
                response = client.request(method, url, headers=headers, json=json, params=params)
        except httpx.TimeoutException as exc:
            last_error = f"{method} {redact(url)} timed out: {exc}"
            if attempt < retries:
                logger.warning("provider request timeout, retrying (attempt %s): %s", attempt + 1, redact(url))
                _backoff_sleep(attempt)
                continue
            raise ProviderHttpError(ErrorKind.TIMEOUT, last_error) from exc
        except httpx.HTTPError as exc:
            last_error = f"{method} {redact(url)} failed: {exc}"
            if attempt < retries:
                logger.warning("provider request error, retrying (attempt %s): %s", attempt + 1, redact(url))
                _backoff_sleep(attempt)
                continue
            raise ProviderHttpError(ErrorKind.UNKNOWN, last_error) from exc

        if response.status_code >= 400:
            kind = _classify(response.status_code)
            if _retryable(kind) and attempt < retries:
                logger.warning(
                    "provider http %s, retrying (attempt %s): %s", response.status_code, attempt + 1, redact(url)
                )
                _backoff_sleep(attempt)
                continue
            raise ProviderHttpError(
                kind,
                f"{method} {redact(url)} -> {response.status_code}: {redact(response.text[:500])}",
                status_code=response.status_code,
            )
        return response

    # Unreachable in practice (the loop always returns or raises) but keeps
    # type checkers and linters honest about the function's return type.
    raise ProviderHttpError(ErrorKind.UNKNOWN, last_error or f"{method} {redact(url)} failed")


def post_json(
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    json: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: Optional[float] = None,
    max_retries: Optional[int] = None,
) -> Dict[str, Any]:
    """POST and return the parsed JSON body, or raise `ProviderHttpError`."""
    response = _request("POST", url, headers=headers, json=json, params=params, timeout=timeout, max_retries=max_retries)
    return _parse_json(response, url)


def get_json(
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: Optional[float] = None,
    max_retries: Optional[int] = None,
) -> Dict[str, Any]:
    """GET and return the parsed JSON body, or raise `ProviderHttpError`."""
    response = _request("GET", url, headers=headers, params=params, timeout=timeout, max_retries=max_retries)
    return _parse_json(response, url)


def post_bytes(
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    json: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: Optional[float] = None,
    max_retries: Optional[int] = None,
) -> bytes:
    """POST and return the raw response body.

    A few vendor endpoints (notably TTS) respond with the generated audio
    itself rather than a JSON envelope — this shares the same retry/backoff
    and error classification as `post_json` without assuming a JSON body.
    """
    response = _request("POST", url, headers=headers, json=json, params=params, timeout=timeout, max_retries=max_retries)
    return response.content


def _parse_json(response: httpx.Response, url: str) -> Dict[str, Any]:
    try:
        return response.json()
    except ValueError as exc:
        raise ProviderHttpError(ErrorKind.BAD_REQUEST, f"Non-JSON response from {redact(url)}") from exc


def download_to_file(
    url: str,
    dest_path: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    timeout: Optional[float] = None,
    max_retries: Optional[int] = None,
) -> str:
    """Stream a generated asset (video/image/audio URL) to a local path.

    Used after a provider returns a result URL — we pull it once into our
    own storage (`app.services.storage`) rather than linking the vendor's
    URL directly, since those are frequently short-lived signed URLs.
    """
    timeout_s, retries = _resolved(timeout, max_retries)
    last_error: Optional[str] = None
    for attempt in range(retries + 1):
        try:
            with httpx.stream("GET", url, headers=headers, timeout=timeout_s) as response:
                if response.status_code >= 400:
                    kind = _classify(response.status_code)
                    if _retryable(kind) and attempt < retries:
                        _backoff_sleep(attempt)
                        continue
                    raise ProviderHttpError(
                        kind, f"GET {redact(url)} -> {response.status_code}", status_code=response.status_code
                    )
                Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
                with open(dest_path, "wb") as fh:
                    for chunk in response.iter_bytes():
                        fh.write(chunk)
                return dest_path
        except httpx.TimeoutException as exc:
            last_error = f"GET {redact(url)} timed out: {exc}"
            if attempt < retries:
                _backoff_sleep(attempt)
                continue
            raise ProviderHttpError(ErrorKind.TIMEOUT, last_error) from exc
        except httpx.HTTPError as exc:
            last_error = f"GET {redact(url)} failed: {exc}"
            if attempt < retries:
                _backoff_sleep(attempt)
                continue
            raise ProviderHttpError(ErrorKind.UNKNOWN, last_error) from exc

    raise ProviderHttpError(ErrorKind.UNKNOWN, last_error or f"GET {redact(url)} failed")
