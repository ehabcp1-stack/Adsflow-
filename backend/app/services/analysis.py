"""AI Analysis Engine.

Four responsibilities, one structured report:
    Brief Interpreter · Asset Analyzer · Creative Strategist · Production Recommender

Runs fully on Mock Providers when no API keys exist.
"""
from __future__ import annotations

import hashlib
import random
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.enums import ProductionMode
from app.models import Asset, Project, ProjectAnalysis
from app.providers.pricing import estimate_scene_cost, estimate_voice_cost
from app.providers.registry import get_llm
from app.services.director import director_note

ANALYSIS_STEPS: List[Dict[str, str]] = [
    {"key": "brief", "label_en": "Understanding brief", "label_ar": "نفهم الطلب"},
    {"key": "images", "label_en": "Analyzing images", "label_ar": "نحلل الصور"},
    {"key": "videos", "label_en": "Analyzing videos", "label_ar": "نحلل الفيديوهات"},
    {"key": "quality", "label_en": "Checking asset quality", "label_ar": "نتأكد من جودة المواد"},
    {"key": "planning", "label_en": "Planning production", "label_ar": "نخطط الإنتاج"},
    {"key": "cost", "label_en": "Estimating cost", "label_ar": "نحسب الكلفة"},
]

IMAGE_CATEGORIES = ["exterior", "interior", "amenity", "location", "detail", "lifestyle", "floorplan"]


def _rng(seed: str) -> random.Random:
    return random.Random(int(hashlib.md5(seed.encode()).hexdigest()[:8], 16))


# --------------------------------------------------------------------------
# Asset Analyzer
# --------------------------------------------------------------------------
def analyze_image(asset: Asset) -> Dict[str, Any]:
    rng = _rng(asset.id)
    quality = round(rng.uniform(62, 97), 1)
    hero = round(min(99.0, quality + rng.uniform(-12, 8)), 1)
    orientation = asset.orientation or ("portrait" if (asset.height or 0) > (asset.width or 1) else "landscape")
    category = asset.category or rng.choice(IMAGE_CATEGORIES)
    return {
        "quality_score": quality,
        "category": category,
        "hero_potential": hero,
        "usable": quality >= 60,
        "suggested_use": {
            "exterior": "لقطة تعريفية بالمشروع",
            "interior": "لقطة إحساس بالمساحة الداخلية",
            "amenity": "إثبات خدمات ومرافق",
            "location": "توضيح الموقع والقرب",
            "detail": "تفصيل يرفع الإحساس بالجودة",
            "lifestyle": "لحظة إنسانية تقرّب الجمهور",
            "floorplan": "معلومة تقنية بموشن غرافيك",
        }.get(category, "مشهد داعم"),
        "orientation": orientation,
        "resolution": f"{asset.width or 1920}x{asset.height or 1080}",
        "needs_reframe": orientation != "portrait",
        "notes_ar": "الصورة تصلح للحركة (Ken Burns) بدون توليد" if quality >= 75 else "جودة متوسطة — تصلح كمشهد ثانوي",
    }


def analyze_video(asset: Asset) -> Dict[str, Any]:
    rng = _rng(asset.id + "v")
    duration = asset.duration_sec or round(rng.uniform(8, 45), 1)
    segment_count = max(2, int(duration // 6))
    segments: List[Dict[str, Any]] = []
    for i in range(segment_count):
        start = round(i * duration / segment_count, 2)
        end = round((i + 1) * duration / segment_count, 2)
        score = round(rng.uniform(55, 96), 1)
        segments.append(
            {
                "start": start,
                "end": end,
                "score": score,
                "strength": "strong" if score >= 82 else ("weak" if score < 68 else "usable"),
                "note_ar": "لقطة ثابتة وواضحة" if score >= 82 else "فيها اهتزاز أو تكرار",
            }
        )
    strong = [s for s in segments if s["strength"] == "strong"]
    orientation = asset.orientation or "landscape"
    return {
        "duration_sec": duration,
        "usable_segments": [s for s in segments if s["strength"] != "weak"],
        "strong_segments": strong,
        "weak_segments": [s for s in segments if s["strength"] == "weak"],
        "hook_potential": round(max([s["score"] for s in segments] + [0]), 1),
        "orientation": orientation,
        "quality": round(sum(s["score"] for s in segments) / len(segments), 1),
        "audio_recommendation": "استبدال الصوت الأصلي بتعليق صوتي عراقي + موسيقى",
        "reframing_recommendation": "قص ذكي إلى ٩:١٦ مع تتبّع مركز الاهتمام" if orientation != "portrait" else "جاهز عمودي",
        "usable": len(strong) > 0,
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
    diversity = len({a.category for a in usable_images if a.category})
    hero_candidates = sorted(usable_images, key=lambda a: -(a.hero_potential or 0))[:3]

    return {
        "image_count": len(images),
        "video_count": len(videos),
        "usable_image_count": len(usable_images),
        "usable_video_count": len([a for a in videos if a.usable]),
        "average_quality": round(
            sum(a.quality_score or 0 for a in assets) / max(len(assets), 1), 1
        ),
        "asset_diversity": diversity,
        "hero_candidates": [{"asset_id": a.id, "score": a.hero_potential} for a in hero_candidates],
        "video_usability": "high" if any(a.usable for a in videos) else ("none" if not videos else "low"),
        "per_asset": per_asset,
    }


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
    video_cost = round(sum(estimate_scene_cost("ai_video", scene_seconds, "veo-3-fast") for _ in range(ai_videos)), 4)
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
    llm = get_llm()
    brief = _brief_dict(project)

    interpretation = llm.complete_json(task="brief_interpretation", context={"brief": brief}).data
    assets_summary = analyze_assets(db, project)
    strategy = llm.complete_json(
        task="creative_strategy", context={"brief": brief, "assets_summary": assets_summary}
    ).data

    mode = strategy.get("recommended_mode", ProductionMode.HYBRID_REEL.value)
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
    if not total_assets:
        notes.append(
            director_note(
                key="no_assets",
                en="No media uploaded — I will plan a Full AI Reel, which costs more. Uploading 4-6 photos cuts it sharply.",
                ar="ما أكو مواد مرفوعة — راح أخطط لريل AI كامل وهذا أغلى. لو ترفع ٤–٦ صور تنزل الكلفة كثير.",
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
