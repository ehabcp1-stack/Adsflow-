"""Asset ingestion and real analysis.

This is the boundary between "a file the browser sent us" and "an Asset row
the rest of the product can trust". Everything the browser claims — filename,
declared size, declared content-type — is only ever used to pick a safe name
and a first guess; every column that matters downstream (dimensions,
duration, orientation, mime type, whether the file even decodes) is read back
from the bytes that were actually written to storage via `app.media.probe`,
never from the request.

Analysis is split from ingestion on purpose: `ingest_asset` stores the file
and fills the facts a probe can give for free; `analyze_asset` runs the
heavier Pillow/FFmpeg measurement pass and can be re-run later (a route calls
it again) without re-uploading anything.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from PIL import Image, ImageFilter, ImageStat, UnidentifiedImageError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AdFlowError
from app.media.ffmpeg import run_ffmpeg
from app.media.motion import recommend_motion
from app.media.probe import ACCEPTED_EXTENSIONS, MediaInfo, guess_mime, kind_for_extension, probe_media
from app.media.remix import extract_segment_thumbnail
from app.media.shots import _frame_metrics, analyze_video as shots_analyze_video
from app.models import Asset
from app.services.storage import get_storage

log = logging.getLogger("adflow.services.assets")

#: Fallback cap when app.core.config hasn't grown MAX_UPLOAD_MB yet. See the
#: module docstring in the task brief: config.py is owned by another engineer
#: right now, so this is read defensively rather than assumed to exist.
_DEFAULT_MAX_UPLOAD_MB = 400

#: A "quiet" segment (in dB relative to full scale) reads as ambient/room
#: tone rather than meaningful speech or an intentional sound cue. This is a
#: threshold picked by ear on typical phone-recorded real-estate footage, not
#: a calibrated loudness standard.
_AUDIO_IMPORTANT_DBFS = -35.0


# --------------------------------------------------------------------------
# Errors — bilingual, matching the house style in app.core.errors
# --------------------------------------------------------------------------
class UnsupportedMediaError(AdFlowError):
    code = "unsupported_media"
    http_status = 415


class PayloadTooLargeError(AdFlowError):
    code = "payload_too_large"
    http_status = 413


class EmptyUploadError(AdFlowError):
    code = "empty_upload"
    http_status = 400


class CorruptMediaError(AdFlowError):
    code = "corrupt_media"
    http_status = 422


# --------------------------------------------------------------------------
# Filename safety
# --------------------------------------------------------------------------
_SAFE_STEM = re.compile(r"[^A-Za-z0-9._\-؀-ۿ]+")  # allow Arabic filenames too


def sanitize_filename(filename: Optional[str]) -> str:
    """Turn a browser-supplied filename into a safe storage-key component.

    Never trust it as a path: normalise Windows-style separators, take the
    basename only (defeats `../../etc/passwd.jpg`-style traversal), and strip
    anything outside a conservative allowlist so it can never be interpreted
    as a directory component or a hidden/dotfile by anything downstream.
    """
    raw = (filename or "asset").replace("\\", "/")
    name = Path(raw).name or "asset"
    stem, ext = os.path.splitext(name)
    ext = re.sub(r"[^A-Za-z0-9.]", "", ext).lower()
    stem = _SAFE_STEM.sub("_", stem).strip("._") or "asset"
    return f"{stem[:150]}{ext[:10]}"


# --------------------------------------------------------------------------
# Upload validation
# --------------------------------------------------------------------------
def validate_upload(filename: str, size_bytes: int, content_type: Optional[str] = None) -> None:
    """Reject what we already know is wrong before touching storage or disk.

    `content_type` is accepted for the error message only — it is what the
    browser *claims*, and is never used to decide anything; the extension and
    (later) `probe_media` are the only things trusted.
    """
    ext = Path(filename).suffix.lower()
    if ext not in ACCEPTED_EXTENSIONS:
        raise UnsupportedMediaError(
            f"'{ext or 'unknown'}' files aren't supported. Upload a photo, video or audio file.",
            f"صيغة الملف '{ext or 'غير معروفة'}' مو مدعومة — ارفع صورة أو فيديو أو صوت.",
            content_type=content_type,
        )
    if size_bytes <= 0:
        raise EmptyUploadError(
            "This file is empty.",
            "الملف فاضي — ما أكو محتوى نرفعه.",
        )
    max_mb = getattr(settings, "MAX_UPLOAD_MB", _DEFAULT_MAX_UPLOAD_MB)
    max_bytes = max_mb * 1024 * 1024
    if size_bytes > max_bytes:
        raise PayloadTooLargeError(
            f"This file is larger than the {max_mb}MB limit.",
            f"حجم الملف أكبر من الحد المسموح ({max_mb} ميغابايت).",
            max_upload_mb=max_mb,
        )


# --------------------------------------------------------------------------
# Ingestion
# --------------------------------------------------------------------------
def _storage_key(*, organization_id: str, project_id: Optional[str], ext: str) -> str:
    unique = uuid.uuid4().hex
    if project_id:
        return f"projects/{project_id}/assets/{unique}{ext}"
    return f"library/{organization_id}/{unique}{ext}"


def _make_thumbnail(storage: Any, key: str, source_path: str, kind: str, info: MediaInfo) -> Optional[str]:
    """Best-effort real thumbnail. A missing thumbnail must never fail an upload."""
    thumb_key = f"{key}.thumb.jpg"
    try:
        with tempfile.TemporaryDirectory(prefix="adflow-thumb-") as tmp:
            local_thumb = str(Path(tmp) / "thumb.jpg")
            if kind == "video":
                midpoint = max((info.duration_sec or 0.0) / 2.0, 0.0)
                if not extract_segment_thumbnail(source_path, local_thumb, midpoint):
                    return None
            elif kind == "image":
                with Image.open(source_path) as im:
                    im = im.convert("RGB")
                    im.thumbnail((640, 640))
                    im.save(local_thumb, "JPEG", quality=85)
            else:
                return None
            return storage.put_file(thumb_key, local_thumb, "image/jpeg")
    except Exception as exc:  # noqa: BLE001 - a missing thumbnail must never fail ingestion
        log.warning("thumbnail generation failed for %s (%s): %s", key, kind, exc)
        return None


def ingest_asset(
    db: Session,
    *,
    organization_id: str,
    project_id: Optional[str],
    filename: str,
    data_or_path: Union[bytes, str],
    kind_hint: Optional[str] = None,
    is_project_reference: bool = False,
    content_type: Optional[str] = None,
) -> Asset:
    """Store an upload and fill every measurable Asset column from the file itself.

    Rejects files that don't pass `validate_upload`, and rejects files that
    pass validation but don't actually decode (`probe_media(...).ok is False`)
    — corrupt uploads never become Asset rows and never reach storage.
    """
    safe_name = sanitize_filename(filename)
    ext = Path(safe_name).suffix.lower()

    owns_temp = False
    tmp_dir: Optional[str] = None
    if isinstance(data_or_path, (bytes, bytearray)):
        size_bytes = len(data_or_path)
        validate_upload(safe_name, size_bytes, content_type)
        tmp_dir = tempfile.mkdtemp(prefix="adflow-ingest-")
        source_path = str(Path(tmp_dir) / f"source{ext or '.bin'}")
        Path(source_path).write_bytes(data_or_path)
        owns_temp = True
    else:
        source_path = str(data_or_path)
        if not Path(source_path).exists():
            raise EmptyUploadError("Upload not found on disk.", "ما لكينا الملف المرفوع.")
        size_bytes = Path(source_path).stat().st_size
        validate_upload(safe_name, size_bytes, content_type)

    try:
        info = probe_media(source_path)
        if not info.ok:
            log.info("rejected undecodable upload %s: %s", safe_name, info.error)
            raise CorruptMediaError(
                f"This file could not be read as media ({info.error or 'unknown error'}). "
                "It may be corrupt or in an unsupported format.",
                "ما كدرنا نفتح هذا الملف — يمكن يكون تالف أو الصيغة مو مدعومة.",
            )

        kind = info.kind if info.kind != "unknown" else (kind_hint or kind_for_extension(safe_name) or "image")
        mime = guess_mime(safe_name)
        storage = get_storage()
        key = _storage_key(organization_id=organization_id, project_id=project_id, ext=ext)
        url = storage.put_file(key, source_path, mime)
        thumbnail_url = _make_thumbnail(storage, key, source_path, kind, info)

        asset = Asset(
            organization_id=organization_id,
            project_id=project_id,
            kind=kind,
            filename=safe_name,
            storage_key=key,
            url=url,
            thumbnail_url=thumbnail_url,
            mime_type=mime,
            size_bytes=info.size_bytes or size_bytes,
            width=info.width,
            height=info.height,
            duration_sec=info.duration_sec,
            orientation=info.orientation,
            is_project_reference=is_project_reference,
        )
        db.add(asset)
        db.flush()
        return asset
    finally:
        if owns_temp and tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


# --------------------------------------------------------------------------
# Image analysis
# --------------------------------------------------------------------------
def _orientation(width: int, height: int) -> str:
    if not width or not height:
        return "unknown"
    if abs(width - height) / max(width, height) < 0.05:
        return "square"
    return "portrait" if height > width else "landscape"


def _resolution_class(width: int, height: int) -> str:
    """A coarse, honest bucket — not a claim about print quality or sensor size."""
    longest = max(width, height)
    if longest < 720:
        return "low"
    if longest < 1440:
        return "standard"
    if longest < 2600:
        return "high"
    return "very_high"


def _text_present_guess(grey: Image.Image) -> bool:
    """Heuristic only: high-frequency edge density in a horizontal band.

    This looks for the kind of dense, regular edges that on-screen text or a
    caption bar produces — it is NOT text/OCR detection. A busy tiled facade
    or a patterned rug can trip it; a low-contrast caption can be missed.
    Treat the result as "maybe has text", never as ground truth.
    """
    w, h = grey.size
    if w < 8 or h < 8:
        return False
    band = grey.crop((0, int(h * 0.72), w, h))  # lower third — the usual caption zone
    edges = ImageStat.Stat(band.filter(ImageFilter.FIND_EDGES))
    density = edges.stddev[0] / 255.0
    return density > 0.22


def _usable_crop_9_16(width: int, height: int) -> bool:
    """Can a *centred* crop reach 9:16 without throwing away most of the frame?

    Purely a geometry estimate — it has no idea where the subject actually
    is, so it assumes centred content. A wide panorama with an off-centre
    subject can still read `True` here and lose the subject on crop.
    """
    if not width or not height:
        return False
    aspect = width / height
    target = 9 / 16
    retained = (target / aspect) if aspect >= target else (aspect / target)
    return retained >= 0.55


def _motion_potential(width: int, height: int, sharpness: float) -> float:
    """How much headroom a photo-motion (Ken Burns style) move has to work with.

    Depends on spare resolution beyond the 1080x1920 output frame (room to
    pan/zoom without upscaling) and on measured detail (a soft photo shows
    its softening faster once it's moving). Bounded 0..1.
    """
    if not width or not height:
        return 0.3
    spare = min(width / 1080.0, height / 1920.0)
    spare_score = min(max((spare - 1.0) / 1.5, 0.0), 1.0)
    return round(min(max(0.6 * spare_score + 0.4 * sharpness, 0.0), 1.0), 3)


def _visual_category_guess(*, aspect: float, brightness: float, colorfulness: float, contrast: float) -> str:
    """A crude guess from pixel statistics alone — not scene/object recognition.

    Real category detection would need a vision model; this only bins
    brightness/contrast/colour/aspect into the categories the product already
    uses, so it is wrong often enough that `suggested_use` should always be
    re-checked by a human before it drives a paid decision.
    """
    if aspect >= 1.25 and brightness >= 0.5 and colorfulness >= 0.35:
        return "exterior"
    if contrast <= 0.35 and 0.25 <= brightness <= 0.65:
        return "interior"
    if colorfulness >= 0.55 and brightness >= 0.55:
        return "lifestyle"
    if aspect < 0.85:
        return "detail"
    return "amenity"


def analyze_image(path: str) -> Dict[str, Any]:
    """Real, measured photo analysis via Pillow — not a guess dressed up as one.

    Reuses the same brightness/contrast/sharpness/colorfulness measurement
    `app.media.shots._frame_metrics` uses for video frames (imported, not
    duplicated) so a photo's score and a video segment's score are on the
    same scale and genuinely comparable. Everything beyond that raw
    measurement (category, text presence, crop/motion suitability) is a
    named heuristic — see each helper's docstring for exactly what it can
    and can't tell you.

    SVG placeholders (the product's own vector graphics, not customer
    photography — see `app.media.probe`) can't be rasterised by Pillow. They
    are already validated by `probe_media` before this is ever called, so
    rather than failing the whole analysis this returns a clearly-labelled,
    unmeasured default instead of fabricating pixel statistics for pixels
    that were never opened.
    """
    suffix = Path(path).suffix.lower()
    if suffix == ".svg":
        return {
            "measured": False,
            "note": "vector placeholder graphic — not rasterised, no pixel measurement taken",
            "brightness": None, "contrast": None, "sharpness": None, "colorfulness": None,
            "exposure": "unknown", "exposure_ar": "غير مقاس",
            "orientation": "portrait", "aspect": round(9 / 16, 4),
            "resolution_class": "standard", "width": 1080, "height": 1920,
            "quality": 0.7, "quality_score": 70.0,
            "hero_potential": 0.55, "hero_potential_score": 55.0,
            "text_present": False,
            "usable_crop_9_16": True,
            "motion_potential": 0.4,
            "recommended_scene_use": "معلومة أو عرض بموشن غرافيك",
            "recommended_motion": "controlled_zoom",
            "visual_category_guess": "graphic",
        }

    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            width, height = im.size
            # Match app.media.shots._grab_frames' scale (width=320) so scores
            # land on the same metric scale as video-segment scores.
            scaled = im.resize((320, max(int(320 * height / max(width, 1)), 1)))
            metrics = _frame_metrics(scaled)
    except (UnidentifiedImageError, OSError) as exc:
        # probe_media already confirmed this decodes for its own tooling
        # (ffprobe); Pillow failing here is a real, separate signal that the
        # file is unusable for pixel analysis specifically.
        log.warning("Pillow could not open %s: %s", path, exc)
        return {
            "measured": False,
            "error": str(exc),
            "quality": 0.0, "quality_score": 0.0,
            "hero_potential": 0.0, "hero_potential_score": 0.0,
            "usable_crop_9_16": False, "motion_potential": 0.0,
            "text_present": False,
            "orientation": "unknown", "aspect": None, "resolution_class": "unknown",
            "width": None, "height": None,
            "recommended_scene_use": "غير قابل للاستخدام", "recommended_motion": "static",
            "visual_category_guess": "unknown",
            "exposure": "unknown", "exposure_ar": "غير معروف",
        }

    brightness, contrast, sharpness, colorfulness = (
        metrics["brightness"], metrics["contrast"], metrics["sharpness"], metrics["colorfulness"],
    )
    orientation = _orientation(width, height)
    aspect = round(width / height, 4) if height else None

    if brightness < 0.32:
        exposure, exposure_ar = "underexposed", "الإضاءة واطية — الصورة غامقة"
    elif brightness > 0.78:
        exposure, exposure_ar = "overexposed", "الإضاءة زايدة — فيه انحراق بالصورة"
    else:
        exposure, exposure_ar = "well_exposed", "الإضاءة مضبوطة"

    exposure_penalty = max(0.0, 1.0 - abs(brightness - 0.52) * 2.6)
    quality = round(min(max(
        0.34 * sharpness + 0.26 * contrast + 0.22 * exposure_penalty + 0.18 * colorfulness, 0.0
    ), 1.0), 3)
    resolution_class = _resolution_class(width, height)
    resolution_bonus = {"low": -0.1, "standard": 0.0, "high": 0.05, "very_high": 0.08}[resolution_class]
    hero_potential = round(min(max(0.75 * quality + 0.15 * exposure_penalty + resolution_bonus, 0.0), 1.0), 3)
    motion_potential = _motion_potential(width, height, sharpness)
    category_guess = _visual_category_guess(
        aspect=aspect or 1.0, brightness=brightness, colorfulness=colorfulness, contrast=contrast
    )
    scene_use = {
        "exterior": "لقطة تعريفية بالمشروع",
        "interior": "لقطة إحساس بالمساحة الداخلية",
        "amenity": "إثبات خدمات ومرافق",
        "lifestyle": "لحظة إنسانية تقرّب الجمهور",
        "detail": "تفصيل يرفع الإحساس بالجودة",
    }.get(category_guess, "مشهد داعم")

    text_present = _text_present_guess(scaled.convert("L"))

    return {
        "measured": True,
        "brightness": brightness, "contrast": contrast, "sharpness": sharpness, "colorfulness": colorfulness,
        "exposure": exposure, "exposure_ar": exposure_ar,
        "orientation": orientation, "aspect": aspect, "resolution_class": resolution_class,
        "width": width, "height": height,
        "quality": quality, "quality_score": round(quality * 100, 1),
        "hero_potential": hero_potential, "hero_potential_score": round(hero_potential * 100, 1),
        "text_present": text_present,
        "usable_crop_9_16": _usable_crop_9_16(width, height),
        "motion_potential": motion_potential,
        "recommended_scene_use": scene_use,
        "recommended_motion": recommend_motion(
            index=0, orientation=orientation, is_hook=hero_potential >= 0.7,
            purpose="", motion_potential=motion_potential,
        ),
        "visual_category_guess": category_guess,
    }


# --------------------------------------------------------------------------
# Video analysis
# --------------------------------------------------------------------------
_VOLUME_RE = re.compile(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")


def _segment_mean_volume_db(path: str, start: float, end: float, *, max_probe_sec: float = 3.0) -> Optional[float]:
    """Cheap loudness read via FFmpeg's `volumedetect`, bounded to a short window.

    Reading the whole segment would be the honest measurement, but the
    window is capped so this never becomes the slow part of analysis. Returns
    None (never a guessed number) when FFmpeg can't run or produced no
    reading — callers must treat None as "unknown", not as "quiet".
    """
    span = min(max(end - start, 0.1), max_probe_sec)
    try:
        stderr = run_ffmpeg(
            ["-ss", f"{max(start, 0):.3f}", "-t", f"{span:.3f}", "-i", path,
             "-af", "volumedetect", "-vn", "-f", "null", "-"],
            label="assets:volumedetect", timeout=30,
        )
    except Exception as exc:  # noqa: BLE001 - loudness is a bonus signal, never a hard failure
        log.debug("volumedetect failed for %s [%.2f-%.2f]: %s", path, start, end, exc)
        return None
    match = _VOLUME_RE.search(stderr)
    return float(match.group(1)) if match else None


def _reframe_suitability(orientation: str) -> str:
    """Default reframe mode from orientation alone — no subject tracking.

    Landscape defaults to `blur_pad` (keeps the whole original frame, which
    matters for real-estate fidelity — cropping a landscape shot can cut off
    part of the building); portrait/square already fit 9:16 and default to
    a plain `crop`.
    """
    return "crop" if orientation in ("portrait", "square") else "blur_pad"


def analyze_video_asset(path: str, *, thumb_dir: str) -> Dict[str, Any]:
    """Wrap `app.media.shots.analyze_video` with per-segment production guidance.

    All shot-detection and per-segment quality/hook/motion scoring is the
    real engine in `app.media.shots` — this only adds the decisions that
    engine doesn't make: which segment carries meaningful audio (a cheap,
    honestly-labelled loudness read, not audio content understanding), how
    to reframe each segment to 9:16, and a top-level remix plan hint.
    """
    base = shots_analyze_video(path, thumb_dir=thumb_dir)
    if not base.get("ok"):
        return {**base, "usable": False, "quality": 0.0, "hook_potential": 0.0, "remix_plan_hint": None}

    has_audio = bool(base.get("has_audio"))
    segments: List[Dict[str, Any]] = []
    best_index = base.get("best_opening_index")
    keep_indices: List[int] = []
    drop_indices: List[int] = []

    for raw in base["segments"]:
        seg = dict(raw)
        if not has_audio:
            seg["audio_important"], seg["audio_important_basis"] = False, "no_audio"
        else:
            db = _segment_mean_volume_db(path, seg["start"], seg["end"])
            if db is None:
                seg["audio_important"], seg["audio_important_basis"] = None, "unknown"
            else:
                seg["audio_important"] = db > _AUDIO_IMPORTANT_DBFS
                seg["audio_important_basis"] = "measured"
                seg["measured_mean_volume_db"] = db
        seg["reframe_suitability"] = _reframe_suitability(seg.get("orientation", base.get("orientation", "landscape")))
        if seg["recommendation"] == "drop":
            seg["keep_recommendation"] = "remove"
            drop_indices.append(seg["index"])
        else:
            seg["keep_recommendation"] = "keep"
            keep_indices.append(seg["index"])
        if seg["index"] == best_index:
            seg["recommended_use"] = "hook"
        elif seg["strength"] == "weak":
            seg["recommended_use"] = "cut"
        elif seg["strength"] == "strong":
            seg["recommended_use"] = "supporting"
        else:
            seg["recommended_use"] = "b_roll"
        segments.append(seg)

    quality = round(sum(s["quality"] for s in segments) / len(segments), 3) if segments else 0.0
    hook_potential = round(max((s["hook_potential"] for s in segments), default=0.0), 3)

    if best_index is not None and best_index in keep_indices:
        suggested_reorder = [best_index] + [i for i in keep_indices if i != best_index]
    else:
        suggested_reorder = list(keep_indices)

    remix_plan_hint = {
        "original_duration_sec": base["duration_sec"],
        "recommended_final_duration_sec": base["usable_duration_sec"],
        "retain_percent": round(base["retain_ratio"] * 100, 1),
        "strongest_opening_index": best_index,
        "clips_to_keep": keep_indices,
        "clips_to_drop": drop_indices,
        "suggested_reorder": suggested_reorder,
    }

    return {
        **base,
        "segments": segments,
        "quality": quality,
        "hook_potential": hook_potential,
        "usable": base["usable_count"] > 0,
        "remix_plan_hint": remix_plan_hint,
    }


# --------------------------------------------------------------------------
# Dispatch + Asset column projection
# --------------------------------------------------------------------------
def analyze_asset(db: Session, asset: Asset) -> Dict[str, Any]:
    """Analyse one asset's stored file and write the result onto the Asset row.

    Idempotent: given the same stored file, both `analyze_image` and
    `analyze_video_asset` are pure measurements with no randomness, so
    running this twice on an unchanged file produces the same verdict.
    Never raises — a weird or unreachable file degrades to
    `usable=False` with the reason recorded in `analysis["error"]` rather
    than failing the request that asked for a re-analysis.
    """
    try:
        if not asset.storage_key:
            raise FileNotFoundError("asset has no storage_key")
        path = get_storage().local_path(asset.storage_key)
        if not path or not Path(path).exists():
            raise FileNotFoundError(f"stored file not found for key {asset.storage_key}")

        if asset.kind == "video":
            with tempfile.TemporaryDirectory(prefix="adflow-analyze-") as tmp:
                result = analyze_video_asset(path, thumb_dir=tmp)
            asset.quality_score = round((result.get("quality") or 0.0) * 100, 1)
            asset.hero_potential = None
            asset.usable = bool(result.get("usable", False))
            asset.category = "video_footage"
            asset.suggested_use = "إعادة إنتاج (Remix) من الفيديو الأصلي" if asset.usable else "ما أكو مقاطع تصلح بهذا الفيديو"
        elif asset.kind == "image":
            result = analyze_image(path)
            quality01 = result.get("quality", 0.0)
            asset.quality_score = round(quality01 * 100, 1)
            asset.hero_potential = round((result.get("hero_potential") or 0.0) * 100, 1)
            asset.usable = bool(result.get("measured", True)) and quality01 >= 0.45
            asset.category = result.get("visual_category_guess")
            asset.suggested_use = result.get("recommended_scene_use")
        else:
            result = {"ok": False, "measured": False, "error": f"analysis not implemented for kind='{asset.kind}'"}
            asset.usable = False
    except Exception as exc:  # noqa: BLE001 - a bad file must degrade the asset, never crash the caller
        log.warning("analysis failed for asset %s (%s): %s", asset.id, asset.kind, exc)
        result = {"ok": False, "measured": False, "error": str(exc)}
        asset.usable = False
        asset.quality_score = 0.0

    asset.analysis = result
    db.flush()
    return result


def asset_payload(asset: Asset) -> Dict[str, Any]:
    """The dict the API returns for one asset — superset of the pre-existing shape."""
    analysis = asset.analysis or {}
    return {
        "id": asset.id,
        "kind": asset.kind,
        "filename": asset.filename,
        "url": asset.url,
        "thumbnail_url": asset.thumbnail_url or asset.url,
        "mime_type": asset.mime_type,
        "size_bytes": asset.size_bytes,
        "width": asset.width,
        "height": asset.height,
        "duration_sec": asset.duration_sec,
        "orientation": asset.orientation,
        "quality_score": asset.quality_score,
        "hero_potential": asset.hero_potential,
        "usable": asset.usable,
        "category": asset.category,
        "suggested_use": asset.suggested_use,
        "analysis": analysis,
        "project_id": asset.project_id,
        "is_generated": asset.is_generated,
        "is_project_reference": asset.is_project_reference,
        "tags": asset.tags,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
        # -- additions: real facts and re-analysis affordance --------------
        "aspect_ratio": round(asset.width / asset.height, 4) if (asset.width and asset.height) else None,
        "is_analyzed": bool(analysis),
        "analysis_error": analysis.get("error"),
    }
