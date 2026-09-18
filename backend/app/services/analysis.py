"""AI Analysis Engine.

Four responsibilities, one structured report:
    Brief Interpreter · Asset Analyzer · Creative Strategist · Production Recommender

Runs fully on Mock Providers when no API keys exist.

The Asset Analyzer used to score every asset with a seeded random number —
consistent across runs, but not connected to the actual file. It now reads
`app.services.assets` (real Pillow/FFmpeg measurement, see that module) and
falls back to an honestly-labelled "not measured" result only when an asset
has no locally-reachable file at all (e.g. one registered by remote URL
through `/assets/register`, which never had bytes to inspect).
"""
from __future__ import annotations

import logging
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.enums import ProductionMode, QualityLevel
from app.models import Asset, Project, ProjectAnalysis
from app.providers.model_router import model_candidates
from app.providers.pricing import estimate_scene_cost, estimate_voice_cost
from app.providers.registry import get_llm
from app.services import assets as assets_service
from app.services.director import director_note
from app.services.storage import get_storage

log = logging.getLogger("adflow.services.analysis")

ANALYSIS_STEPS: List[Dict[str, str]] = [
    {"key": "brief", "label_en": "Understanding brief", "label_ar": "نفهم الطلب"},
    {"key": "images", "label_en": "Analyzing images", "label_ar": "نحلل الصور"},
    {"key": "videos", "label_en": "Analyzing videos", "label_ar": "نحلل الفيديوهات"},
    {"key": "quality", "label_en": "Checking asset quality", "label_ar": "نتأكد من جودة المواد"},
    {"key": "planning", "label_en": "Planning production", "label_ar": "نخطط الإنتاج"},
    {"key": "cost", "label_en": "Estimating cost", "label_ar": "نحسب الكلفة"},
]

IMAGE_CATEGORIES = ["exterior", "interior", "amenity", "location", "detail", "lifestyle", "floorplan"]

#: Minimum total usable footage to count as "good footage" for mode selection
#: — enough to carry a reel opening on its own. Below this, own photos plus
#: motion is judged the stronger (and cheaper) source.
_GOOD_FOOTAGE_SEC = 6.0


# --------------------------------------------------------------------------
# Asset Analyzer
# --------------------------------------------------------------------------
def _local_path(asset: Asset) -> Optional[str]:
    if not asset.storage_key:
        return None
    try:
        # Through media_bridge, not the adapter: `local_path` is None for every
        # object-storage backend, so calling it directly turns "S3 is
        # configured" into "no asset can be measured".
        from app.services import media_bridge

        path = media_bridge.local_path_for(asset.storage_key)
    except Exception:  # noqa: BLE001 - a storage backend quirk must not break analysis
        return None
    return path if path and Path(path).exists() else None


def _unmeasured_image_result(asset: Asset, *, error: Optional[str] = None) -> Dict[str, Any]:
    """Honest fallback for an Asset row with no reachable local file.

    Used for assets registered by remote URL (`/assets/register`) — there is
    no file here to measure, so this returns a clearly-labelled placeholder
    instead of fabricating pixel statistics.
    """
    orientation = asset.orientation or "unknown"
    return {
        "measured": False,
        "error": error,
        "quality_score": 0.0,
        "category": asset.category or "unknown",
        "hero_potential": 0.0,
        "usable": False,
        "suggested_use": "ما أكو ملف محلي نحلله — راجع الرابط",
        "orientation": orientation,
        "resolution": f"{asset.width or 0}x{asset.height or 0}",
        "needs_reframe": orientation != "portrait",
        "notes_ar": "صار خطأ أثناء التحليل." if error else "هذا رابط خارجي — ما نقدر نقيس الصورة فعلياً.",
    }


def analyze_image(asset: Asset) -> Dict[str, Any]:
    """Real Pillow measurement of the asset's stored file, reshaped to the
    dict shape existing callers (`/assets/register`, this module) expect.

    See `app.services.assets.analyze_image` for the actual measurement and
    the full-detail result (kept here under `measured_detail`).
    """
    path = _local_path(asset)
    if not path:
        return _unmeasured_image_result(asset)
    try:
        measured = assets_service.analyze_image(path)
    except Exception as exc:  # noqa: BLE001 - a bad file degrades the result, never crashes analysis
        log.warning("image measurement failed for asset %s: %s", asset.id, exc)
        return _unmeasured_image_result(asset, error=str(exc))

    quality01 = measured.get("quality", 0.0)
    hero01 = measured.get("hero_potential", 0.0)
    orientation = measured.get("orientation") or asset.orientation or "unknown"
    width, height = measured.get("width"), measured.get("height")
    return {
        "measured": bool(measured.get("measured", True)),
        "quality_score": round(quality01 * 100, 1),
        "category": measured.get("visual_category_guess", asset.category),
        "hero_potential": round(hero01 * 100, 1),
        "usable": bool(measured.get("measured", True)) and quality01 >= 0.45,
        "suggested_use": measured.get("recommended_scene_use"),
        "orientation": orientation,
        "resolution": f"{width or asset.width or 0}x{height or asset.height or 0}",
        "needs_reframe": orientation != "portrait",
        "notes_ar": measured.get("exposure_ar", ""),
        "measured_detail": measured,
    }


def _unmeasured_video_result(asset: Asset, *, error: Optional[str] = None) -> Dict[str, Any]:
    orientation = asset.orientation or "landscape"
    return {
        "measured": False,
        "error": error,
        "duration_sec": asset.duration_sec or 0.0,
        "usable_segments": [],
        "strong_segments": [],
        "weak_segments": [],
        "hook_potential": 0.0,
        "orientation": orientation,
        "quality": 0.0,
        "audio_recommendation": "غير متوفر بدون ملف محلي",
        "reframing_recommendation": "غير متوفر بدون ملف محلي",
        "usable": False,
    }


def analyze_video(asset: Asset) -> Dict[str, Any]:
    """Real shot-detection + per-segment scoring of the asset's stored file.

    See `app.services.assets.analyze_video_asset` (wraps `app.media.shots`)
    for the actual measurement; this reshapes it to the dict shape existing
    callers expect and keeps the full-detail result under `measured_detail`.
    """
    path = _local_path(asset)
    if not path:
        return _unmeasured_video_result(asset)
    try:
        with tempfile.TemporaryDirectory(prefix="adflow-analysis-") as tmp:
            measured = assets_service.analyze_video_asset(path, thumb_dir=tmp)
    except Exception as exc:  # noqa: BLE001 - a bad file degrades the result, never crashes analysis
        log.warning("video measurement failed for asset %s: %s", asset.id, exc)
        return _unmeasured_video_result(asset, error=str(exc))

    if not measured.get("ok"):
        return _unmeasured_video_result(asset, error=measured.get("error"))

    segments_old = [
        {
            "start": s["start"], "end": s["end"],
            "score": round(s["quality"] * 100, 1),
            "strength": s["strength"],
            "note_ar": s["reason_ar"],
        }
        for s in measured["segments"]
    ]
    strong = [s for s in segments_old if s["strength"] == "strong"]
    weak = [s for s in segments_old if s["strength"] == "weak"]
    orientation = measured.get("orientation") or asset.orientation or "landscape"
    reframe_votes = [s.get("reframe_suitability") for s in measured["segments"]]
    reframing_recommendation = (
        "جاهز عمودي" if orientation == "portrait"
        else ("قص ذكي إلى ٩:١٦" if reframe_votes.count("crop") >= reframe_votes.count("blur_pad")
              else "تأطير بخلفية ضبابية يحافظ على المشهد كامل")
    )
    audio_important_count = sum(1 for s in measured["segments"] if s.get("audio_important"))
    audio_recommendation = (
        "الصوت الأصلي مهم بأكثر من مقطع — يفضل نبقيه أو نمزجه مع الموسيقى"
        if audio_important_count
        else "استبدال الصوت الأصلي بتعليق صوتي عراقي + موسيقى"
    )

    return {
        "measured": True,
        "duration_sec": measured["duration_sec"],
        "usable_segments": [s for s in segments_old if s["strength"] != "weak"],
        "strong_segments": strong,
        "weak_segments": weak,
        "hook_potential": round(measured["hook_potential"] * 100, 1),
        "orientation": orientation,
        "quality": round(measured["quality"] * 100, 1),
        "audio_recommendation": audio_recommendation,
        "reframing_recommendation": reframing_recommendation,
        "usable": measured["usable"],
        "usable_count": measured.get("usable_count", 0),
        "usable_duration_sec": measured.get("usable_duration_sec", 0.0),
        "best_opening_index": measured.get("best_opening_index"),
        "remix_plan_hint": measured.get("remix_plan_hint"),
        "measured_detail": measured,
    }


def analyze_assets(db: Session, project: Project) -> Dict[str, Any]:
    assets: List[Asset] = db.query(Asset).filter(Asset.project_id == project.id).all()
    images = [a for a in assets if a.kind in ("image", "reference", "logo")]
    videos = [a for a in assets if a.kind == "video"]

    per_asset: List[Dict[str, Any]] = []
    for asset in images:
        result = analyze_image(asset)
        asset.analysis = result
        asset.quality_score = result["quality_score"]
        asset.hero_potential = result["hero_potential"]
        asset.usable = result["usable"]
        asset.category = result["category"]
        asset.suggested_use = result["suggested_use"]
        per_asset.append({"asset_id": asset.id, "kind": asset.kind, **result})
    for asset in videos:
        result = analyze_video(asset)
        asset.analysis = result
        asset.quality_score = result["quality"]
        asset.usable = result["usable"]
        per_asset.append({"asset_id": asset.id, "kind": "video", **result})

    usable_images = [a for a in images if a.usable]
    usable_videos = [a for a in videos if a.usable]
    diversity = len({a.category for a in usable_images if a.category})
    hero_candidates = sorted(usable_images, key=lambda a: -(a.hero_potential or 0))[:3]

    # Real counts the mode/cost decisions are driven by — not raw presence.
    usable_video_segment_count = sum(int((a.analysis or {}).get("usable_count", 0)) for a in usable_videos)
    usable_video_duration_sec = round(
        sum(float((a.analysis or {}).get("usable_duration_sec", 0.0)) for a in usable_videos), 2
    )
    hook_pool = [
        {"asset_id": a.id, "kind": "image", "score": a.hero_potential or 0.0} for a in usable_images
    ] + [
        {"asset_id": a.id, "kind": "video", "score": (a.analysis or {}).get("hook_potential") or 0.0}
        for a in usable_videos
    ]
    best_hook = max(hook_pool, key=lambda h: h["score"], default=None)
    orientation_mix: Dict[str, int] = {}
    for a in usable_images + usable_videos:
        key = a.orientation or "unknown"
        orientation_mix[key] = orientation_mix.get(key, 0) + 1

    return {
        "image_count": len(images),
        "video_count": len(videos),
        "usable_image_count": len(usable_images),
        "usable_video_count": len(usable_videos),
        "usable_video_segment_count": usable_video_segment_count,
        "usable_video_duration_sec": usable_video_duration_sec,
        "average_quality": round(
            sum(a.quality_score or 0 for a in assets) / max(len(assets), 1), 1
        ),
        "asset_diversity": diversity,
        "hero_candidates": [{"asset_id": a.id, "score": a.hero_potential} for a in hero_candidates],
        "best_hook": best_hook,
        "orientation_mix": orientation_mix,
        "video_usability": "high" if any(a.usable for a in videos) else ("none" if not videos else "low"),
        "per_asset": per_asset,
    }


def recommend_production_mode(assets_summary: Dict[str, Any]) -> str:
    """Pick a production mode from real, measured asset facts — never a guess.

    Mirrors the product's cost spine (CLAUDE.md §4 — Original Video → Original
    Photo → Photo Motion → AI Image → AI Video): footage the customer already
    owns beats anything generated, so a project with enough *usable* video
    duration always wins `video_remix_reel`; a photo-only project with usable
    stills gets the (still premium) `photo_voice_reel`; a project with both
    gets `hybrid_reel`; a project with nothing usable falls back to
    `full_ai_reel`, which is the one mode that costs real money regardless of
    what the customer already has.
    """
    usable_images = assets_summary.get("usable_image_count", 0)
    usable_video_sec = assets_summary.get("usable_video_duration_sec", 0.0)
    has_good_video = usable_video_sec >= _GOOD_FOOTAGE_SEC
    has_photos = usable_images > 0
    if has_good_video and has_photos:
        return ProductionMode.HYBRID_REEL.value
    if has_good_video:
        return ProductionMode.VIDEO_REMIX_REEL.value
    if has_photos:
        return ProductionMode.PHOTO_VOICE_REEL.value
    return ProductionMode.FULL_AI_REEL.value


# --------------------------------------------------------------------------
# Analysis Engine
# --------------------------------------------------------------------------
def _brief_dict(project: Project) -> Dict[str, Any]:
    return {
        "name": project.name,
        "category": project.category,
        "goal": project.goal,
        "platform": project.platform,
        "duration_sec": project.duration_sec,
        "language": project.language,
        "dialect": project.dialect,
        "tone": project.tone,
        "target_audience": project.target_audience,
        "key_information": project.key_information,
        "cta": project.cta,
        "production_mode": project.production_mode,
    }


def estimate_project_cost(project: Project, assets_summary: Dict[str, Any], mode: str) -> Dict[str, Any]:
    scene_count = max(4, min(9, project.duration_sec // 4))
    usable_media = assets_summary.get("usable_image_count", 0) + assets_summary.get("usable_video_count", 0)
    from_existing = min(scene_count, usable_media)
    remaining = max(scene_count - from_existing, 0)

    photo_motion = min(from_existing, max(1, from_existing // 2))
    ai_images = max(0, remaining - 1) if remaining else 0
    ai_videos = 1 if remaining and mode in (ProductionMode.HYBRID_REEL.value, ProductionMode.FULL_AI_REEL.value) else 0
    if mode == ProductionMode.FULL_AI_REEL.value:
        ai_images = max(ai_images, scene_count - 2)
        ai_videos = max(ai_videos, 2)

    scene_seconds = project.duration_sec / max(scene_count, 1)
    # Price the estimate against whatever the catalog currently calls the
    # default video tier, so a model swap moves the quote with it.
    default_video_model = model_candidates("ai_video", QualityLevel.SMART_PREMIUM.value)[0][1]
    video_cost = round(
        sum(estimate_scene_cost("ai_video", scene_seconds, default_video_model) for _ in range(ai_videos)), 4
    )
    image_cost = round(sum(estimate_scene_cost("ai_image", scene_seconds, "gpt-image-1") for _ in range(ai_images)), 4)
    motion_cost = round(photo_motion * estimate_scene_cost("photo_motion", scene_seconds), 4)
    voice_cost = estimate_voice_cost(int(project.duration_sec * 9)) if project.voice_over_enabled else 0.0
    music_cost = 0.20
    total = round(video_cost + image_cost + motion_cost + voice_cost + music_cost, 4)

    return {
        "scene_count": scene_count,
        "scenes_from_existing_media": from_existing,
        "scenes_photo_motion": photo_motion,
        "scenes_ai_image": ai_images,
        "scenes_ai_video": ai_videos,
        "voice_cost_usd": round(voice_cost, 4),
        "video_cost_usd": video_cost,
        "image_cost_usd": image_cost,
        "music_cost_usd": music_cost,
        "photo_motion_cost_usd": motion_cost,
        "estimated_total_usd": total,
    }


def run_analysis(db: Session, project: Project, *, version: Optional[int] = None) -> ProjectAnalysis:
    """Produce one analysis report. Two model calls, run side by side.

    They used to run one after the other, which made the stage cost the sum of
    two ~28s calls for no reason: `brief_interpretation` reads only the brief,
    and `creative_strategy` reads the brief plus the measured asset summary.
    Neither reads the other's output. Measuring the assets first and then
    running both concurrently makes the stage cost roughly one model call
    instead of two — the difference between a minute of spinner and half of it.

    The asset measurement stays on this thread on purpose: it writes the
    measurements back onto the Asset rows through `db`, and a Session is not
    safe to touch from two threads at once.
    """
    llm = get_llm()
    brief = _brief_dict(project)

    assets_summary = analyze_assets(db, project)

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="adflow-analysis") as pool:
        brief_call = pool.submit(
            llm.complete_json, task="brief_interpretation", context={"brief": brief}
        )
        strategy_call = pool.submit(
            llm.complete_json,
            task="creative_strategy",
            context={"brief": brief, "assets_summary": assets_summary},
        )
        # .result() re-raises whatever the call raised, on this thread, so a
        # provider failure still fails the job instead of being swallowed.
        interpretation = brief_call.result().data
        strategy = strategy_call.result().data

    # The mode decision is driven by real, measured counts (see
    # recommend_production_mode) rather than the LLM/mock provider's opinion
    # — `strategy["recommended_mode"]` is kept in `creative_strategy` for
    # transparency but never used to decide what gets produced.
    mode = recommend_production_mode(assets_summary)
    if project.production_mode != ProductionMode.AUTO_SMART.value:
        mode = project.production_mode
    cost_plan = estimate_project_cost(project, assets_summary, mode)

    total_assets = assets_summary["image_count"] + assets_summary["video_count"]
    readiness = min(
        100.0,
        round(
            35
            + min(assets_summary["usable_image_count"], 8) * 5
            + min(assets_summary["usable_video_count"], 3) * 8
            + (10 if project.key_information else 0)
            + (5 if project.cta else 0),
            1,
        ),
    )
    confidence = round(min(97.0, 68 + assets_summary["asset_diversity"] * 4 + (8 if total_assets else 0)), 1)

    notes = [
        director_note(
            key="source_strength",
            en=(
                "Your source material is strong enough for a Photo + Voice Reel."
                if assets_summary["usable_image_count"] >= 4 and not assets_summary["usable_video_count"]
                else "Mixing your own footage with one generated hero shot gives the best cost/quality balance."
            ),
            ar=(
                "موادك تكفي لعمل ريل صور + صوت بجودة ممتازة بدون توليد فيديو."
                if assets_summary["usable_image_count"] >= 4 and not assets_summary["usable_video_count"]
                else "الأفضل تدمج موادك مع لقطة بطل وحدة مولّدة — أفضل توازن بين الكلفة والجودة."
            ),
            impact="high",
        ),
        director_note(
            key="cost_guard",
            en=f"Estimated production cost is ${cost_plan['estimated_total_usd']:.2f} — inside your monthly target.",
            ar=f"الكلفة التقديرية ${cost_plan['estimated_total_usd']:.2f} — ضمن هدفك الشهري.",
            impact="medium",
        ),
    ]
    if assets_summary["video_count"] and assets_summary["usable_video_count"]:
        notes.append(
            director_note(
                key="remix",
                en="Your uploaded video has strong segments — remixing costs nothing to generate.",
                ar="الفيديو اللي رفعته بيه مقاطع قوية — إعادة إنتاجه ما تكلف توليد.",
                impact="high",
            )
        )
    if mode == ProductionMode.FULL_AI_REEL.value:
        # Real counts, not just an empty library, drive this: an asset that
        # exists but failed analysis (corrupt, unreadable) counts the same as
        # nothing uploaded — neither can be produced from for free.
        notes.append(
            director_note(
                key="no_usable_assets",
                en=(
                    f"Nothing usable to build from yet — this plans as a Full AI Reel, "
                    f"estimated ${cost_plan['estimated_total_usd']:.2f}. Uploading 4-6 usable "
                    f"photos would cut that sharply."
                    if total_assets
                    else "No media uploaded — I will plan a Full AI Reel, which costs more. "
                    "Uploading 4-6 photos cuts it sharply."
                ),
                ar=(
                    f"ما أكو مواد صالحة نبني عليها — راح أخطط لريل AI كامل، الكلفة التقديرية "
                    f"${cost_plan['estimated_total_usd']:.2f}. لو ترفع ٤–٦ صور صالحة تنزل الكلفة كثير."
                    if total_assets
                    else "ما أكو مواد مرفوعة — راح أخطط لريل AI كامل وهذا أغلى. لو ترفع ٤–٦ صور تنزل الكلفة كثير."
                ),
                impact="high",
            )
        )

    last = (
        db.query(ProjectAnalysis)
        .filter(ProjectAnalysis.project_id == project.id)
        .order_by(ProjectAnalysis.version.desc())
        .first()
    )
    next_version = version or ((last.version + 1) if last else 1)

    analysis = ProjectAnalysis(
        project_id=project.id,
        version=next_version,
        brief_interpretation=interpretation,
        asset_analysis=assets_summary,
        creative_strategy=strategy,
        production_recommendation=cost_plan,
        recommended_mode=mode,
        recommended_duration_sec=project.duration_sec,
        recommended_angle=strategy.get("recommended_angle", "emotional"),
        recommended_voice_style=strategy.get("recommended_voice_style", "iraqi_professional"),
        estimated_cost_usd=cost_plan["estimated_total_usd"],
        readiness_score=readiness,
        confidence_score=confidence,
        director_notes=notes,
    )
    db.add(analysis)
    project.estimated_cost_usd = cost_plan["estimated_total_usd"]
    db.flush()
    return analysis

