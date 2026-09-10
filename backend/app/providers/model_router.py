"""Model Router.

Decides provider+model per scene from: scene type, source material, quality
requirement, reference strength, project fidelity, estimated cost, remaining
budget and past provider performance.

CORE PRODUCT PRINCIPLE: never buy expensive AI video just because it exists.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.core.enums import ProductionMethod, QualityLevel
from app.providers.pricing import estimate_scene_cost

#: Ordered candidates per method and quality level: (provider, model)
MODEL_CANDIDATES: Dict[str, Dict[str, List[tuple[str, str]]]] = {
    ProductionMethod.AI_VIDEO.value: {
        QualityLevel.ECONOMY.value: [("seedance", "seedance-1-pro"), ("runway", "runway-gen4-turbo"), ("mock", "mock-video-v1")],
        QualityLevel.SMART_PREMIUM.value: [("veo", "veo-3-fast"), ("runway", "runway-gen4-turbo"), ("mock", "mock-video-v1")],
        QualityLevel.MAXIMUM_QUALITY.value: [("veo", "veo-3"), ("veo", "veo-3-fast"), ("mock", "mock-video-v1")],
    },
    ProductionMethod.AI_IMAGE.value: {
        QualityLevel.ECONOMY.value: [("gemini", "seedream-4"), ("mock", "mock-image-v1")],
        QualityLevel.SMART_PREMIUM.value: [("openai", "gpt-image-1"), ("gemini", "gemini-image"), ("mock", "mock-image-v1")],
        QualityLevel.MAXIMUM_QUALITY.value: [("openai", "gpt-image-1"), ("mock", "mock-image-v1")],
    },
}

LOCAL_METHODS = {
    ProductionMethod.ORIGINAL_VIDEO.value,
    ProductionMethod.ORIGINAL_PHOTO.value,
    ProductionMethod.PHOTO_MOTION.value,
    ProductionMethod.MOTION_GRAPHICS.value,
}


@dataclass
class RoutingDecision:
    method: str
    provider: str
    model: str
    estimated_cost_usd: float
    reason_en: str
    reason_ar: str
    downgraded: bool = False
    compare_candidates: Optional[List[tuple[str, str]]] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "method": self.method,
            "provider": self.provider,
            "model": self.model,
            "estimated_cost_usd": self.estimated_cost_usd,
            "reason_en": self.reason_en,
            "reason_ar": self.reason_ar,
            "downgraded": self.downgraded,
            "compare_candidates": self.compare_candidates or [],
        }


def choose_method(
    *,
    has_original_video: bool,
    has_original_photo: bool,
    is_hero: bool,
    is_hook: bool,
    requested_method: Optional[str] = None,
    quality_level: str = QualityLevel.SMART_PREMIUM.value,
    fidelity_locked: bool = True,
) -> tuple[str, str]:
    """Scene source priority: original video → original photo → photo motion → AI image → AI video."""
    if requested_method:
        return requested_method, "اختيار يدوي من المستخدم"
    if has_original_video:
        return ProductionMethod.ORIGINAL_VIDEO.value, "أكو فيديو أصلي يغطي المشهد — بدون كلفة توليد"
    if has_original_photo:
        if is_hook or is_hero:
            return ProductionMethod.PHOTO_MOTION.value, "صورة أصلية مع حركة مدروسة تعطي إحساس سينمائي بكلفة شبه صفرية"
        return ProductionMethod.ORIGINAL_PHOTO.value, "صورة أصلية بجودة كافية للمشهد"
    if fidelity_locked and not (is_hook or is_hero):
        return ProductionMethod.MOTION_GRAPHICS.value, "ما أكو مادة أصلية — موشن غرافيك أأمن من توليد معمار غير حقيقي"
    if is_hook or is_hero:
        if quality_level == QualityLevel.MAXIMUM_QUALITY.value:
            return ProductionMethod.AI_VIDEO.value, "لقطة بطل: فيديو AI يستاهل الكلفة هنا فقط"
        return ProductionMethod.AI_IMAGE.value, "صورة AI + حركة تعطي ٩٠٪ من النتيجة بجزء من الكلفة"
    return ProductionMethod.AI_IMAGE.value, "مشهد ثانوي: صورة AI أرخص وكافية"


def route(
    *,
    scene: Dict[str, Any],
    quality_level: str = QualityLevel.SMART_PREMIUM.value,
    remaining_budget_usd: float = 999.0,
    provider_performance: Optional[Dict[str, float]] = None,
    reference_strength: float = 0.0,
    available_provider_names: Optional[List[str]] = None,
) -> RoutingDecision:
    method = scene.get("production_method", ProductionMethod.AI_IMAGE.value)
    duration = max(float(scene.get("end_time", 3)) - float(scene.get("start_time", 0)), 1.5)
    performance = provider_performance or {}

    if method in LOCAL_METHODS:
        cost = estimate_scene_cost(method, duration)
        return RoutingDecision(
            method=method, provider="local", model="ffmpeg-pipeline", estimated_cost_usd=cost,
            reason_en="Produced locally from owned media — no provider cost.",
            reason_ar="ينتج محلياً من مادتك — بدون كلفة مزود.",
        )

    candidates = MODEL_CANDIDATES.get(method, {}).get(quality_level) or [("mock", "mock-image-v1")]
    if available_provider_names is not None:
        filtered = [c for c in candidates if c[0] in available_provider_names]
        candidates = filtered or [("mock", "mock-video-v1" if method == ProductionMethod.AI_VIDEO.value else "mock-image-v1")]

    candidates = sorted(candidates, key=lambda c: -performance.get(f"{c[0]}:{c[1]}", 0.0))
    provider, model = candidates[0]
    cost = estimate_scene_cost(method, duration, model)
    downgraded = False
    reason_ar = "أفضل توازن بين الجودة والكلفة لهذا المشهد"

    # Budget guard: downgrade instead of failing.
    if cost > remaining_budget_usd and method == ProductionMethod.AI_VIDEO.value:
        method = ProductionMethod.AI_IMAGE.value
        provider, model = (MODEL_CANDIDATES[method][quality_level] or [("mock", "mock-image-v1")])[0]
        cost = estimate_scene_cost(method, duration, model)
        downgraded = True
        reason_ar = "الميزانية المتبقية ما تكفي لفيديو AI — تم النزول لصورة AI مع حركة"

    compare = None
    if scene.get("is_hook") or scene.get("is_hero"):
        compare = candidates[:2] if len(candidates) > 1 else None

    if reference_strength >= 0.6:
        reason_ar += " — مع الالتزام بمراجع المشروع الحقيقية"

    return RoutingDecision(
        method=method, provider=provider, model=model, estimated_cost_usd=cost,
        reason_en="Chosen by cost/quality routing.", reason_ar=reason_ar,
        downgraded=downgraded, compare_candidates=compare,
    )
