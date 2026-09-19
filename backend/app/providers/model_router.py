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
from app.providers import catalog
from app.providers.pricing import estimate_scene_cost

#: Which catalog quality tiers each quality level will accept, best first.
#: The router used to hold a hand-written (provider, model) table, which meant
#: retiring a vendor needed edits in two files and the two drifted apart. It is
#: now derived from `catalog.py`, so disabling a model there removes it from
#: routing everywhere, and a vendor-retired model can never be routed to.
_TIER_PREFERENCE: Dict[str, tuple[str, ...]] = {
    QualityLevel.ECONOMY.value: ("economy", "standard", "premium", "flagship"),
    QualityLevel.SMART_PREMIUM.value: ("standard", "premium", "economy", "flagship"),
    QualityLevel.MAXIMUM_QUALITY.value: ("flagship", "premium", "standard", "economy"),
}

_METHOD_KIND = {
    ProductionMethod.AI_VIDEO.value: "video",
    ProductionMethod.AI_IMAGE.value: "image",
}


def model_candidates(method: str, quality_level: str) -> List[tuple[str, str]]:
    """Ordered (provider, model) candidates for a method at a quality level.

    Ordering is by how well a model's tier matches the requested level, then by
    the catalog's own `fallback_priority`. The mock always survives at the end
    of the list so routing can never return nothing.
    """
    kind = _METHOD_KIND.get(method)
    if kind is None:
        return [("mock", "mock-image-v1")]
    preference = _TIER_PREFERENCE.get(quality_level, _TIER_PREFERENCE[QualityLevel.SMART_PREMIUM.value])
    rank = {tier: index for index, tier in enumerate(preference)}
    specs = [s for s in catalog.candidates(kind) if s.provider_id != "mock"]
    specs.sort(key=lambda s: (rank.get(s.quality_tier, len(preference)), s.fallback_priority))
    fallback = "mock-video-v1" if kind == "video" else "mock-image-v1"
    return [(s.provider_id, s.model_id) for s in specs] + [("mock", fallback)]

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
    # `requested_method` arrives from the storyboard payload, which is written
    # by a model — not, as the reason string used to claim, by the user. It
    # overrode the entire priority ladder, including with values that name no
    # method this system implements. An unknown one is ignored here and the
    # ladder decides, so a scene can never be planned as something nothing
    # knows how to produce. The schema rejects these at the boundary; this is
    # the second lock, for storyboards written before it existed.
    if requested_method and requested_method in {method.value for method in ProductionMethod}:
        return requested_method, "طريقة محددة مسبقاً للمشهد"
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

    candidates = model_candidates(method, quality_level)
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
        provider, model = model_candidates(method, quality_level)[0]
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
