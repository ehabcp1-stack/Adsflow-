"""Storage abstraction.

Production must never assume local disk — the S3 adapter targets any
S3-compatible endpoint (MinIO in docker-compose, AWS/R2 in production).
Local development uses a clean local adapter served by the API at /media.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Optional, Protocol

from app.core.config import settings


class StorageAdapter(Protocol):
    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str: ...
    def put_file(self, key: str, path: str, content_type: str = "application/octet-stream") -> str: ...
    def url_for(self, key: str) -> str: ...
    def local_path(self, key: str) -> Optional[str]: ...
    def exists(self, key: str) -> bool: ...


class LocalStorage:
    def __init__(self, root: str, public_base: str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.public_base = public_base.rstrip("/")

    def _path(self, key: str) -> Path:
        p = (self.root / key.lstrip("/")).resolve()
        if not str(p).startswith(str(self.root)):
            raise ValueError("Invalid storage key")
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        self._path(key).write_bytes(data)
        return self.url_for(key)

    def put_file(self, key: str, path: str, content_type: str = "application/octet-stream") -> str:
        dst = self._path(key)
        if os.path.abspath(path) != str(dst):
            shutil.copyfile(path, dst)
        return self.url_for(key)

    def url_for(self, key: str) -> str:
        return f"{self.public_base}/{key.lstrip('/')}"

    def local_path(self, key: str) -> Optional[str]:
        return str(self._path(key))

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


class S3Storage:  # pragma: no cover - requires credentials
    def __init__(self) -> None:
        import boto3
        from botocore.config import Config

        self.bucket = settings.S3_BUCKET
        # botocore's defaults are 60s connect + 60s read with up to five
        # attempts: about five minutes per object, and this client is called
        # once per asset with nothing above it holding a clock. Twelve assets
        # is an hour of a job sitting at "understanding the brief" with no
        # error, because `media_bridge._materialize_remote` swallows the
        # failure and returns None. Media fetches are bounded here so that a
        # slow bucket degrades one asset instead of the whole stage.
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            region_name=settings.S3_REGION,
            config=Config(
                connect_timeout=settings.S3_CONNECT_TIMEOUT_SEC,
                read_timeout=settings.S3_READ_TIMEOUT_SEC,
                retries={"max_attempts": settings.S3_MAX_ATTEMPTS, "mode": "standard"},
            ),
        )

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
        return self.url_for(key)

    def put_file(self, key: str, path: str, content_type: str = "application/octet-stream") -> str:
        self.client.upload_file(path, self.bucket, key, ExtraArgs={"ContentType": content_type})
        return self.url_for(key)

    def url_for(self, key: str) -> str:
        """The URL a browser should use — which is not the S3 API endpoint.

        On Cloudflare R2 (and most S3-compatible providers) the endpoint that
        accepts uploads is private: `https://<account>.r2.cloudflarestorage.com`
        answers signed API calls, not public GETs. Public reads come from a
        separate host — an r2.dev bucket URL or a custom domain. Building media
        URLs from the API endpoint produces links that 403 in the browser while
        every upload succeeds, which looks like a rendering bug and is not.

        So `PUBLIC_MEDIA_BASE_URL` wins whenever it is set; the endpoint is only
        a fallback for a local MinIO where both happen to be the same host.
        """
        public = (settings.PUBLIC_MEDIA_BASE_URL or "").rstrip("/")
        if public:
            return f"{public}/{key.lstrip('/')}"
        base = (settings.S3_ENDPOINT_URL or "").rstrip("/")
        return f"{base}/{self.bucket}/{key.lstrip('/')}" if base else f"s3://{self.bucket}/{key}"

    def local_path(self, key: str) -> Optional[str]:
        return None

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False


_storage: Optional[StorageAdapter] = None


def get_storage() -> StorageAdapter:
    global _storage
    if _storage is None:
        if settings.STORAGE_BACKEND == "s3":
            _storage = S3Storage()
        else:
            _storage = LocalStorage(settings.STORAGE_LOCAL_DIR, settings.PUBLIC_MEDIA_BASE_URL)
    return _storage
