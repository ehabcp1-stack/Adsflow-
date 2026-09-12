"""Real ingestion + analysis tests — run against the actual fixtures.

No mocked media pipeline here on purpose: FFmpeg/FFprobe/Pillow all run for
real (see conftest.py — only ENABLE_LOCAL_RENDER, the *production render*
switch, is disabled in tests; probing and analysis are unaffected by it).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.core.enums import ProductionMode
from app.models import Asset
from app.services import assets as assets_service
from app.services.analysis import recommend_production_mode

FIXTURES = Path(__file__).parent / "fixtures"
API = "/api/v1"


def _bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# --------------------------------------------------------------------------
# Filename sanitisation
# --------------------------------------------------------------------------
def test_path_traversal_filename_is_sanitised():
    assert assets_service.sanitize_filename("../../etc/passwd.jpg") == "passwd.jpg"
    assert assets_service.sanitize_filename("..\\..\\windows\\evil.jpg") == "evil.jpg"
    assert "/" not in assets_service.sanitize_filename("a/b/c.png")


# --------------------------------------------------------------------------
# Upload validation
# --------------------------------------------------------------------------
def test_unsupported_extension_rejected():
    with pytest.raises(assets_service.UnsupportedMediaError):
        assets_service.validate_upload("virus.exe", 1024, "application/octet-stream")


def test_empty_upload_rejected():
    with pytest.raises(assets_service.EmptyUploadError):
        assets_service.validate_upload("photo.jpg", 0, "image/jpeg")


def test_oversized_upload_rejected():
    max_mb = getattr(assets_service.settings, "MAX_UPLOAD_MB", 400)
    with pytest.raises(assets_service.PayloadTooLargeError):
        assets_service.validate_upload("photo.jpg", (max_mb * 1024 * 1024) + 1, "image/jpeg")


# --------------------------------------------------------------------------
# Ingestion — real files, real probing
# --------------------------------------------------------------------------
def test_corrupt_file_is_rejected_and_leaves_no_asset_row(db, org):
    before = db.query(Asset).count()
    with pytest.raises(assets_service.CorruptMediaError):
        assets_service.ingest_asset(
            db,
            organization_id=org.id,
            project_id=None,
            filename="broken.jpg",
            data_or_path=b"these are not real jpeg bytes, just garbage 0123456789",
        )
    db.commit()
    assert db.query(Asset).count() == before


def test_ingest_fills_columns_from_the_probed_file_not_the_request(db, org):
    """The request lies (wrong kind_hint, wrong content_type) — the stored
    columns must reflect what's actually in the file, not what was claimed."""
    asset = assets_service.ingest_asset(
        db,
        organization_id=org.id,
        project_id=None,
        filename="../../etc/passwd.jpg",  # traversal attempt
        data_or_path=_bytes("photo_landscape.jpg"),
        kind_hint="video",  # deliberately wrong
        content_type="application/pdf",  # deliberately wrong
    )
    db.commit()

    assert asset.filename == "passwd.jpg"  # sanitised, no directory parts
    assert ".." not in asset.storage_key and "/" not in asset.filename
    assert asset.kind == "image"  # from probe_media, not the bogus kind_hint
    assert asset.mime_type == "image/jpeg"  # from the real extension, not the bogus content_type
    assert (asset.width, asset.height) == (1920, 1080)  # real JPEG dimensions
    assert asset.orientation == "landscape"
    assert asset.size_bytes == len(_bytes("photo_landscape.jpg"))


def test_ingest_generates_a_real_thumbnail_for_video(db, org):
    asset = assets_service.ingest_asset(
        db,
        organization_id=org.id,
        project_id=None,
        filename="clip.mp4",
        data_or_path=_bytes("sample_video.mp4"),
    )
    db.commit()
    assert asset.kind == "video"
    assert asset.duration_sec and 11.5 < asset.duration_sec < 12.5
    assert asset.thumbnail_url  # extract_segment_thumbnail actually produced a file


# --------------------------------------------------------------------------
# Image analysis
# --------------------------------------------------------------------------
def test_image_analysis_scores_are_in_unit_range_and_orientation_is_measured():
    landscape = assets_service.analyze_image(str(FIXTURES / "photo_landscape.jpg"))
    portrait = assets_service.analyze_image(str(FIXTURES / "photo_portrait.jpg"))

    for result in (landscape, portrait):
        assert 0.0 <= result["quality"] <= 1.0
        assert 0.0 <= result["hero_potential"] <= 1.0
        assert 0.0 <= result["motion_potential"] <= 1.0
        assert result["measured"] is True

    assert landscape["orientation"] == "landscape"
    assert portrait["orientation"] == "portrait"
    assert portrait["width"], portrait["height"]
    assert portrait["height"] > portrait["width"]


def test_image_analysis_recommends_a_real_motion_preset():
    result = assets_service.analyze_image(str(FIXTURES / "photo_interior.jpg"))
    from app.media.motion import MOTION_PRESETS

    assert result["recommended_motion"] in MOTION_PRESETS


# --------------------------------------------------------------------------
# Video analysis
# --------------------------------------------------------------------------
def test_video_analysis_finds_three_segments_and_a_best_opening_index():
    with tempfile.TemporaryDirectory() as tmp:
        result = assets_service.analyze_video_asset(str(FIXTURES / "sample_video.mp4"), thumb_dir=tmp)

    assert result["ok"] is True
    assert result["segment_count"] == 3
    assert len(result["segments"]) == 3
    best = result["remix_plan_hint"]["strongest_opening_index"]
    assert best is not None
    assert 0 <= best < 3
    # Every segment got the new per-segment guidance fields.
    for seg in result["segments"]:
        assert seg["reframe_suitability"] in ("crop", "blur_pad")
        assert seg["keep_recommendation"] in ("keep", "remove")
        assert seg["audio_important_basis"] in ("measured", "unknown", "no_audio")


# --------------------------------------------------------------------------
# analyze_asset — dispatch, idempotency, honest failure
# --------------------------------------------------------------------------
def test_analyze_asset_is_idempotent_for_an_image(db, org):
    asset = assets_service.ingest_asset(
        db, organization_id=org.id, project_id=None,
        filename="photo.jpg", data_or_path=_bytes("photo_landscape.jpg"),
    )
    db.commit()

    first = assets_service.analyze_asset(db, asset)
    first_quality, first_usable, first_category = asset.quality_score, asset.usable, asset.category
    second = assets_service.analyze_asset(db, asset)

    assert first == second
    assert asset.quality_score == first_quality
    assert asset.usable == first_usable
    assert asset.category == first_category


def _stable_video_verdict(result: dict) -> dict:
    """Strip the parts that are expected to change between runs by design —
    each call gets its own scratch thumbnail directory (see analyze_asset),
    so segment thumbnail paths differ even though the measurement is the
    same. Idempotency is about the *verdict*, not the temp-file bookkeeping.
    """
    return {
        "quality": result["quality"],
        "hook_potential": result["hook_potential"],
        "usable": result["usable"],
        "usable_count": result["usable_count"],
        "remix_plan_hint": result["remix_plan_hint"],
        "segments": [
            {k: v for k, v in seg.items() if k not in ("thumbnail",)}
            for seg in result["segments"]
        ],
    }


def test_analyze_asset_is_idempotent_for_a_video(db, org):
    asset = assets_service.ingest_asset(
        db, organization_id=org.id, project_id=None,
        filename="clip.mp4", data_or_path=_bytes("sample_video.mp4"),
    )
    db.commit()

    first = assets_service.analyze_asset(db, asset)
    first_quality_score = asset.quality_score
    second = assets_service.analyze_asset(db, asset)

    assert _stable_video_verdict(first) == _stable_video_verdict(second)
    assert asset.quality_score == first_quality_score
    assert asset.usable is True


def test_analyze_asset_never_raises_on_a_missing_file(db, org):
    asset = Asset(organization_id=org.id, kind="image", filename="ghost.jpg", storage_key="does/not/exist.jpg")
    db.add(asset)
    db.flush()

    result = assets_service.analyze_asset(db, asset)  # must not raise
    assert asset.usable is False
    assert result.get("error")


# --------------------------------------------------------------------------
# Production-mode recommendation — driven by real counts
# --------------------------------------------------------------------------
def test_recommends_photo_voice_reel_for_photos_only():
    summary = {"usable_image_count": 4, "usable_video_duration_sec": 0.0}
    assert recommend_production_mode(summary) == ProductionMode.PHOTO_VOICE_REEL.value


def test_recommends_video_remix_reel_for_good_footage():
    summary = {"usable_image_count": 0, "usable_video_duration_sec": 20.0}
    assert recommend_production_mode(summary) == ProductionMode.VIDEO_REMIX_REEL.value


def test_recommends_hybrid_reel_for_a_mix():
    summary = {"usable_image_count": 3, "usable_video_duration_sec": 20.0}
    assert recommend_production_mode(summary) == ProductionMode.HYBRID_REEL.value


def test_recommends_full_ai_reel_when_nothing_is_usable():
    summary = {"usable_image_count": 0, "usable_video_duration_sec": 0.0}
    assert recommend_production_mode(summary) == ProductionMode.FULL_AI_REEL.value


# --------------------------------------------------------------------------
# API — upload end-to-end
# --------------------------------------------------------------------------
def test_upload_through_api_returns_2xx_and_appears_in_library(client):
    files = [("files", ("interior.jpg", _bytes("photo_interior.jpg"), "image/jpeg"))]
    response = client.post(f"{API}/assets/upload", files=files, data={"kind": "image"})
    assert response.status_code == 201
    body = response.json()
    asset = body["items"][0]
    assert asset["width"] and asset["height"]
    assert asset["mime_type"] == "image/jpeg"
    assert 0.0 <= (asset["quality_score"] or 0) <= 100.0

    listed = client.get(f"{API}/assets").json()
    assert any(a["id"] == asset["id"] for a in listed["items"])


def test_upload_rejects_corrupt_file_through_api(client):
    files = [("files", ("bad.jpg", b"totally not a jpeg", "image/jpeg"))]
    response = client.post(f"{API}/assets/upload", files=files, data={"kind": "image"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "corrupt_media"


def test_reanalyze_route_recomputes_and_returns_the_same_verdict(client):
    files = [("files", ("landscape2.jpg", _bytes("photo_landscape_2.jpg"), "image/jpeg"))]
    uploaded = client.post(f"{API}/assets/upload", files=files, data={"kind": "image"}).json()
    asset = uploaded["items"][0]

    again = client.post(f"{API}/assets/{asset['id']}/analyze").json()
    assert again["quality_score"] == asset["quality_score"]
    assert again["usable"] == asset["usable"]
