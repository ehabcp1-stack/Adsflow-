"""Object storage and Postgres: the four things that only break in production.

Every one of these passed on SQLite + local disk and failed the first time the
product ran on Postgres + S3, which is the combination it will actually be
deployed on. They are pinned here because that gap is invisible in development.
"""
from __future__ import annotations

import math

import pytest

from app.core.config import settings
from app.core.db import _dumps, _json_safe
from app.media.audio import SILENCE_FLOOR_DB, _finite
from app.services import media_bridge


# --------------------------------------------------------------------------
# Public URLs vs the S3 API endpoint
# --------------------------------------------------------------------------
def test_media_urls_use_the_public_host_not_the_api_endpoint(monkeypatch):
    """On R2 the upload endpoint is private; public reads come from elsewhere.

    Building media URLs from the API endpoint gives links that 403 in the
    browser while every upload reports success.
    """
    from app.services.storage import S3Storage

    monkeypatch.setattr(settings, "S3_ENDPOINT_URL", "https://acct.r2.cloudflarestorage.com")
    monkeypatch.setattr(settings, "S3_BUCKET", "adflow")
    monkeypatch.setattr(settings, "PUBLIC_MEDIA_BASE_URL", "https://media.tadafq.com")

    storage = S3Storage.__new__(S3Storage)  # no client needed for url_for
    storage.bucket = "adflow"
    url = storage.url_for("projects/abc/renders/v1/master.mp4")
    assert url == "https://media.tadafq.com/projects/abc/renders/v1/master.mp4"
    assert "r2.cloudflarestorage.com" not in url


def test_the_endpoint_is_only_a_fallback(monkeypatch):
    """A local MinIO where both hosts are the same must still work."""
    from app.services.storage import S3Storage

    monkeypatch.setattr(settings, "S3_ENDPOINT_URL", "http://127.0.0.1:9000")
    monkeypatch.setattr(settings, "PUBLIC_MEDIA_BASE_URL", "")
    storage = S3Storage.__new__(S3Storage)
    storage.bucket = "adflow"
    assert storage.url_for("a/b.mp4") == "http://127.0.0.1:9000/adflow/a/b.mp4"


# --------------------------------------------------------------------------
# Recovering the key from a URL
# --------------------------------------------------------------------------
def test_a_path_style_url_does_not_keep_the_bucket_in_the_key(monkeypatch):
    """Path-style S3 URLs are /<bucket>/<key>; the bucket is not part of the key."""
    monkeypatch.setattr(settings, "S3_BUCKET", "adflow")
    monkeypatch.setattr(settings, "PUBLIC_MEDIA_BASE_URL", "http://127.0.0.1:9000")
    key = media_bridge.key_from_url("http://127.0.0.1:9000/adflow/projects/x/master.mp4")
    assert key == "projects/x/master.mp4"


def test_a_public_domain_url_round_trips(monkeypatch):
    monkeypatch.setattr(settings, "S3_BUCKET", "adflow")
    monkeypatch.setattr(settings, "PUBLIC_MEDIA_BASE_URL", "https://media.tadafq.com")
    key = media_bridge.key_from_url("https://media.tadafq.com/projects/x/master.mp4")
    assert key == "projects/x/master.mp4"


def test_a_bucket_named_like_a_folder_is_not_stripped_twice(monkeypatch):
    """Only a leading bucket segment goes; an inner match must survive."""
    monkeypatch.setattr(settings, "S3_BUCKET", "projects")
    monkeypatch.setattr(settings, "PUBLIC_MEDIA_BASE_URL", "")
    assert media_bridge.key_from_url("http://h/projects/projects/x.mp4") == "projects/x.mp4"


# --------------------------------------------------------------------------
# Values JSON cannot hold
# --------------------------------------------------------------------------
def test_infinity_never_reaches_a_json_column():
    """SQLite stores `Infinity` happily; Postgres rejects the whole insert."""
    payload = {"true_peak_dbfs": float("-inf"), "lra": float("nan"), "ok": -13.7}
    assert _json_safe(payload) == {"true_peak_dbfs": None, "lra": None, "ok": -13.7}
    assert "Infinity" not in _dumps(payload)
    assert "NaN" not in _dumps(payload)


def test_the_guard_reaches_into_nested_structures():
    nested = {"stages": [{"peak": float("inf")}, {"peak": -1.5}]}
    assert _json_safe(nested) == {"stages": [{"peak": None}, {"peak": -1.5}]}


def test_arabic_survives_the_serializer():
    assert "مدينة" in _dumps({"name": "مدينة الورد"})


def test_silence_is_recorded_as_a_floor_not_as_infinity():
    """The true peak of digital silence is -inf, which is true and unstorable."""
    assert _finite(float("-inf")) == SILENCE_FLOOR_DB
    assert _finite(float("nan")) is None
    assert _finite(-13.7) == -13.7
    assert math.isfinite(_finite(float("-inf")))


# --------------------------------------------------------------------------
# Asset analysis must not ask the adapter for a local path
# --------------------------------------------------------------------------
def test_asset_analysis_goes_through_the_bridge_not_the_adapter(db, make_project, monkeypatch, tmp_path):
    """`local_path` is None for every object-storage backend by definition.

    Calling it directly turned "S3 is configured" into "no asset can ever be
    measured" — every upload analysed as unusable.
    """
    from PIL import Image

    from app.models import Asset
    from app.services import assets as assets_service

    real = tmp_path / "photo.jpg"
    Image.new("RGB", (1080, 1920), (90, 120, 160)).save(real, "JPEG")

    project = make_project(name="تخزين بعيد")
    asset = Asset(
        organization_id=project.organization_id, project_id=project.id, kind="image",
        filename="photo.jpg", storage_key="demo/x/photo.jpg", url="https://cdn/x/photo.jpg",
        mime_type="image/jpeg", width=1080, height=1920,
    )
    db.add(asset)
    db.flush()

    # Exactly what S3 does: the adapter cannot hand back a path, the bridge can.
    monkeypatch.setattr(assets_service.get_storage(), "local_path", lambda key: None, raising=False)
    monkeypatch.setattr(media_bridge, "local_path_for", lambda key: str(real))

    result = assets_service.analyze_asset(db, asset)

    # The point is that the file was REACHED and measured. Whether a flat test
    # image then scores as usable is the quality judgement doing its job.
    assert not (asset.analysis or {}).get("error"), result
    assert "brightness" in result and "contrast" in result
    assert asset.quality_score is not None
