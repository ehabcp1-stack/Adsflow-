"""Media Library, Brand Kits, and product metadata (options, providers, dialects)."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.enums import (
    CampaignGoal,
    Dialect,
    EditingStyle,
    Language,
    Platform,
    ProductionMode,
    ProjectState,
    QualityLevel,
    StrategicAngle,
    Tone,
    WorkflowStage,
)
from app.core.errors import NotFound
from app.core.security import get_current_user
from app.models import Asset, BrandKit, Project, User, VoiceProfile
from app.providers.registry import provider_status
from app.schemas import AssetRegister, BrandKitPayload
from app.services import assets as assets_service
from app.services.analysis import analyze_image, analyze_video
from app.services.assets import asset_payload
from app.services.dialect import list_presets
from app.services.editing import CAPTION_TEMPLATES, EDITING_STYLES
from app.services.exports import VARIANTS as EXPORT_VARIANTS
from app.services.voices import ensure_demo_voices, voice_payload

log = logging.getLogger("adflow.api.library")

router = APIRouter(tags=["library"])


# --------------------------------------------------------------------------
# Assets / Media Library
# --------------------------------------------------------------------------
# `asset_payload` now lives in app.services.assets (imported above) so the
# ingestion service and this API return the exact same shape. Re-exported
# under this name for anything importing it from here.


@router.get("/assets")
def list_assets(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    project_id: Optional[str] = Query(default=None),
    kind: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    query = db.query(Asset).filter(Asset.organization_id == user.organization_id)
    if project_id:
        query = query.filter(Asset.project_id == project_id)
    if kind:
        query = query.filter(Asset.kind == kind)
    items = query.order_by(Asset.created_at.desc()).all()
    return {"items": [asset_payload(a) for a in items], "total": len(items)}


@router.post("/assets/upload", status_code=201)
async def upload_assets(
    files: List[UploadFile] = File(...),
    project_id: Optional[str] = Form(default=None),
    kind: str = Form(default="image"),
    is_project_reference: bool = Form(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Store each upload for real, reject what doesn't decode, analyse the rest.

    `assets_service.ingest_asset` probes the stored file before trusting
    anything the browser claimed (name/size/type), so a corrupt or oversized
    upload raises a bilingual `AdFlowError` here and never becomes an Asset
    row. Analysis runs synchronously and capped (real Pillow/FFmpeg work, no
    randomness) — for very large videos this is the honest trade-off noted in
    `app.services.assets`: moving it to `app.services.jobs` is a follow-up,
    not something this endpoint pretends to already do.
    """
    created: List[Asset] = []
    for upload in files:
        data = await upload.read()
        asset = assets_service.ingest_asset(
            db,
            organization_id=user.organization_id,
            project_id=project_id,
            filename=upload.filename or "asset",
            data_or_path=data,
            kind_hint=kind,
            is_project_reference=is_project_reference,
            content_type=upload.content_type,
        )
        assets_service.analyze_asset(db, asset)
        created.append(asset)
    db.commit()
    return {"items": [asset_payload(a) for a in created]}


@router.post("/assets/{asset_id}/analyze")
def reanalyze_asset(
    asset_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """Re-run real measurement on one already-uploaded asset.

    Useful after a partial or failed analysis, or simply to confirm the
    stored verdict still holds — it is idempotent, so calling it again never
    changes an unchanged file's result.
    """
    asset = db.get(Asset, asset_id)
    if not asset or asset.organization_id != user.organization_id:
        raise NotFound("Asset not found.", "المادة غير موجودة.")
    assets_service.analyze_asset(db, asset)
    db.commit()
    return asset_payload(asset)


@router.post("/assets/register", status_code=201)
def register_asset(
    payload: AssetRegister, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    asset = Asset(
        organization_id=user.organization_id,
        project_id=payload.project_id,
        kind=payload.kind,
        filename=payload.filename or payload.url.rsplit("/", 1)[-1],
        url=payload.url,
        thumbnail_url=payload.thumbnail_url,
        width=payload.width,
        height=payload.height,
        duration_sec=payload.duration_sec,
        orientation="portrait" if (payload.height or 0) >= (payload.width or 0) else "landscape",
        is_project_reference=payload.is_project_reference,
        tags=payload.tags,
    )
    db.add(asset)
    db.flush()
    asset.analysis = analyze_video(asset) if payload.kind == "video" else analyze_image(asset)
    db.commit()
    return asset_payload(asset)


@router.delete("/assets/{asset_id}")
def delete_asset(asset_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Dict[str, Any]:
    asset = db.get(Asset, asset_id)
    if not asset or asset.organization_id != user.organization_id:
        raise NotFound("Asset not found.", "المادة غير موجودة.")
    db.delete(asset)
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------
# Brand Kits
# --------------------------------------------------------------------------
def brand_payload(kit: BrandKit) -> Dict[str, Any]:
    return {
        "id": kit.id,
        "name": kit.name,
        "name_ar": kit.name_ar,
        "logo_url": kit.logo_url,
        "primary_color": kit.primary_color,
        "secondary_color": kit.secondary_color,
        "accent_color": kit.accent_color,
        "font_arabic": kit.font_arabic,
        "font_latin": kit.font_latin,
        "caption_style": kit.caption_style,
        "editing_style": kit.editing_style,
        "voice_profile_id": kit.voice_profile_id,
        "music_profile": kit.music_profile,
        "cta_template": kit.cta_template,
        "end_screen_template": kit.end_screen_template,
        "phone": kit.phone,
        "website": kit.website,
        "social_handles": kit.social_handles,
        "pronunciation_rules": kit.pronunciation_rules,
        "forbidden_phrases": kit.forbidden_phrases,
        "preferred_phrases": kit.preferred_phrases,
        "is_default": kit.is_default,
        "created_at": kit.created_at.isoformat() if kit.created_at else None,
    }


@router.get("/brands")
def list_brands(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Dict[str, Any]:
    kits = db.query(BrandKit).filter(BrandKit.organization_id == user.organization_id).all()
    return {"items": [brand_payload(k) for k in kits], "total": len(kits)}


@router.post("/brands", status_code=201)
def create_brand(
    payload: BrandKitPayload, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    if payload.is_default:
        for kit in db.query(BrandKit).filter(BrandKit.organization_id == user.organization_id).all():
            kit.is_default = False
    kit = BrandKit(organization_id=user.organization_id, **payload.model_dump())
    db.add(kit)
    db.commit()
    return brand_payload(kit)


@router.patch("/brands/{brand_id}")
def update_brand(
    brand_id: str, payload: BrandKitPayload, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    kit = db.get(BrandKit, brand_id)
    if not kit or kit.organization_id != user.organization_id:
        raise NotFound("Brand kit not found.", "هوية العلامة غير موجودة.")
    data = payload.model_dump()
    if data.get("is_default"):
        for other in db.query(BrandKit).filter(BrandKit.organization_id == user.organization_id).all():
            other.is_default = False
    for field, value in data.items():
        setattr(kit, field, value)
    db.commit()
    return brand_payload(kit)


@router.delete("/brands/{brand_id}")
def delete_brand(brand_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Dict[str, Any]:
    kit = db.get(BrandKit, brand_id)
    if not kit or kit.organization_id != user.organization_id:
        raise NotFound("Brand kit not found.", "هوية العلامة غير موجودة.")
    db.query(Project).filter(Project.brand_kit_id == kit.id).update({"brand_kit_id": None})
    db.delete(kit)
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------
# Metadata / options / settings
# --------------------------------------------------------------------------
def _options(enum_cls, labels: Dict[str, str]) -> List[Dict[str, str]]:
    return [{"value": item.value, "label_en": item.value.replace("_", " ").title(), "label_ar": labels.get(item.value, item.value)} for item in enum_cls]


@router.get("/meta/options")
def meta_options() -> Dict[str, Any]:
    return {
        "goals": _options(CampaignGoal, {
            "leads": "استفسارات", "sales": "مبيعات", "awareness": "تعريف", "offer": "عرض", "launch": "إطلاق",
        }),
        "platforms": _options(Platform, {
            "instagram_reels": "ريلز إنستغرام", "facebook_reels": "ريلز فيسبوك", "tiktok": "تيك توك", "multi": "متعدد",
        }),
        "languages": _options(Language, {
            "iraqi_arabic": "عربي عراقي", "msa": "عربي فصيح", "english": "إنكليزي",
        }),
        "dialects": _options(Dialect, {
            "iraqi_professional": "عراقي احترافي", "iraqi_luxury": "عراقي فخم", "iraqi_emotional": "عراقي عاطفي",
            "iraqi_direct_sales": "عراقي مبيعات", "iraqi_friendly": "عراقي ودود", "iraqi_youth": "عراقي شبابي",
            "none": "بدون لهجة",
        }),
        "tones": _options(Tone, {
            "ai_decide": "الذكاء يقرر", "luxury": "فخم", "emotional": "عاطفي", "direct": "مباشر",
            "friendly": "ودود", "professional": "احترافي",
        }),
        "production_modes": _options(ProductionMode, {
            "auto_smart": "ذكي تلقائي", "photo_voice_reel": "ريل صور + صوت", "video_remix_reel": "إعادة إنتاج فيديو",
            "hybrid_reel": "ريل هجين", "full_ai_reel": "ريل AI كامل", "offer_info_reel": "ريل عرض/معلومات",
        }),
        "quality_levels": _options(QualityLevel, {
            "economy": "اقتصادي", "smart_premium": "بريميوم ذكي", "maximum_quality": "أعلى جودة",
        }),
        "angles": _options(StrategicAngle, {
            "emotional": "عاطفي", "luxury": "فخامة", "direct_response": "استجابة مباشرة", "lifestyle": "أسلوب حياة",
            "investment": "استثمار", "information_offer": "معلومة/عرض", "ugc_like": "محتوى طبيعي", "authority_trust": "ثقة ومصداقية",
        }),
        "editing_styles": EDITING_STYLES,
        "caption_templates": CAPTION_TEMPLATES,
        "export_variants": EXPORT_VARIANTS,
        "durations": [15, 30, 45, 60],
        "categories": [
            {"value": "real_estate", "label_en": "Real Estate", "label_ar": "عقارات"},
            {"value": "retail", "label_en": "Retail", "label_ar": "تجزئة"},
            {"value": "services", "label_en": "Services", "label_ar": "خدمات"},
            {"value": "restaurant", "label_en": "Restaurant", "label_ar": "مطاعم"},
            {"value": "medical", "label_en": "Medical", "label_ar": "طبي"},
            {"value": "education", "label_en": "Education", "label_ar": "تعليم"},
            {"value": "other", "label_en": "Other", "label_ar": "غير ذلك"},
        ],
        "states": [state.value for state in ProjectState],
        "stages": [stage.value for stage in WorkflowStage],
        "dialect_presets": list_presets(),
    }


@router.get("/meta/providers")
def meta_providers() -> Dict[str, Any]:
    return {
        "providers": provider_status(),
        "force_mock": settings.FORCE_MOCK_PROVIDERS,
        "env_keys": [
            "OPENAI_API_KEY", "GEMINI_API_KEY", "ELEVENLABS_API_KEY",
            "RUNWAY_API_KEY", "VEO_API_KEY", "SEEDANCE_API_KEY", "MUSIC_API_KEY",
        ],
    }


@router.get("/meta/voices")
def meta_voices(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Dict[str, Any]:
    profiles = ensure_demo_voices(db, user.organization_id)
    db.commit()
    return {"items": [voice_payload(p) for p in profiles]}


@router.get("/settings")
def get_settings_view(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Dict[str, Any]:
    from app.services.costs import monthly_spend

    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "locale": user.locale,
            "director_mode": user.director_mode,
        },
        "organization": {
            "id": user.organization.id,
            "name": user.organization.name,
            "name_ar": user.organization.name_ar,
            "parent_brand": user.organization.parent_brand,
            "monthly_budget_usd": user.organization.monthly_budget_usd,
        },
        "spend": monthly_spend(db, user.organization_id),
        "providers": provider_status(),
        "defaults": {
            "project_budget_usd": settings.DEFAULT_PROJECT_BUDGET_USD,
            "quality_level": settings.DEFAULT_QUALITY_LEVEL,
            "qc_approve_threshold": settings.QC_APPROVE_THRESHOLD,
            "qc_review_threshold": settings.QC_REVIEW_THRESHOLD,
            "scene_quality_threshold": settings.SCENE_QUALITY_THRESHOLD,
            "storage_backend": settings.STORAGE_BACKEND,
            "job_backend": settings.JOB_BACKEND,
        },
        "voice_profiles": [voice_payload(p) for p in db.query(VoiceProfile).all()],
    }
