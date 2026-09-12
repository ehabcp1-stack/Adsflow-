"""Bridge between stored media (URLs / storage keys) and the local files the
media engine needs.

`app.media` works on real paths. Storage may be a local directory today and an
S3 bucket tomorrow, so every path the renderer touches goes through here:
resolve a URL to a readable local file (downloading it once if the backend is
remote), and publish a produced file back into storage under a stable key.

Keeping this in one module is what lets `STORAGE_BACKEND=s3` work without a
single change inside the render code.
"""
from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import unquote, urlparse

from app.core.config import settings
from app.services.storage import get_storage

log = logging.getLogger("adflow.media_bridge")

#: Downloads are cached for the life of the process — a single render touches
#: the same source photo several times (motion clip, thumbnail, QC).
_download_cache: Dict[str, str] = {}


def key_from_url(url: Optional[str]) -> Optional[str]:
    """Recover the storage key from a media URL we produced."""
    if not url:
        return None
    if "://" not in url:
        return url.lstrip("/")
    path = unquote(urlparse(url).path)
    marker = "/media/"
    if marker in path:
        return path.split(marker, 1)[1]
    base_path = urlparse(settings.PUBLIC_MEDIA_BASE_URL).path.rstrip("/")
    if base_path and path.startswith(base_path):
        return path[len(base_path):].lstrip("/")
    key = path.lstrip("/")
    # An S3 endpoint URL is path-style: /<bucket>/<key>. Keeping the bucket in
    # the key makes every later lookup miss — the object is at "projects/…",
    # not "adflow/projects/…".
    bucket = (settings.S3_BUCKET or "").strip("/")
    if bucket and key.startswith(f"{bucket}/"):
        return key[len(bucket) + 1:]
    return key


def local_path_for(url_or_key: Optional[str]) -> Optional[str]:
    """Return a readable local path for stored media, or None.

    With the local adapter this is a direct filesystem path. With S3 the object
    is fetched once into a temp file and reused.
    """
    if not url_or_key:
        return None
    if Path(url_or_key).exists():  # already a local path (tests, seeding)
        return url_or_key
    key = key_from_url(url_or_key)
    if not key:
        return None
    if key in _download_cache and Path(_download_cache[key]).exists():
        return _download_cache[key]

    storage = get_storage()
    direct = None
    try:
        direct = storage.local_path(key)
    except Exception as exc:  # noqa: BLE001 - a bad key must not crash a render
        log.warning("storage.local_path failed for %s: %s", key, exc)
    if direct and Path(direct).exists():
        return direct

    # Remote backend: materialise the object once.
    fetched = _materialize_remote(key)
    if fetched:
        _download_cache[key] = fetched
    return fetched


def _materialize_remote(key: str) -> Optional[str]:
    storage = get_storage()
    client = getattr(storage, "client", None)
    bucket = getattr(storage, "bucket", None)
    if client is None or bucket is None:
        return None
    suffix = Path(key).suffix or ".bin"
    handle = tempfile.NamedTemporaryFile(prefix="adflow-src-", suffix=suffix, delete=False)
    handle.close()
    try:  # pragma: no cover - requires S3 credentials
        client.download_file(bucket, key, handle.name)
        return handle.name
    except Exception as exc:  # noqa: BLE001
        log.warning("could not fetch %s from object storage: %s", key, exc)
        Path(handle.name).unlink(missing_ok=True)
        return None


def publish(local_file: str, key: str, content_type: str = "application/octet-stream") -> str:
    """Put a produced file into storage and return its public URL."""
    return get_storage().put_file(key, local_file, content_type)


def output_path(key: str) -> str:
    """Where the renderer should write, so that publishing is a no-op locally."""
    storage = get_storage()
    try:
        path = storage.local_path(key)
    except Exception:  # noqa: BLE001
        path = None
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        return path
    temp_dir = tempfile.mkdtemp(prefix="adflow-out-")
    return str(Path(temp_dir) / Path(key).name)


CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}


def content_type_for(path_or_key: str) -> str:
    return CONTENT_TYPES.get(Path(path_or_key).suffix.lower(), "application/octet-stream")


def render_to_storage(key: str, render_fn: Any) -> Dict[str, Any]:
    """Run ``render_fn(local_path)`` then publish the result under ``key``.

    ``render_fn`` receives the path it must write to and may return a dict of
    metadata, which is merged into the returned record.
    """
    target = output_path(key)
    meta = render_fn(target) or {}
    if not Path(target).exists():
        raise RuntimeError(f"renderer produced no file for {key}")
    url = publish(target, key, content_type_for(key))
    return {**(meta if isinstance(meta, dict) else {}), "key": key, "path": target, "url": url}


def copy_into_storage(source: str, key: str) -> str:
    """Bring an external file (a provider download) into our own storage."""
    target = output_path(key)
    if Path(source).resolve() != Path(target).resolve():
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return publish(target, key, content_type_for(key))
