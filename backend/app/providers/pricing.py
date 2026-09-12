"""Cost model.

Prices are per-operation USD estimates used by the Budget Guard and the
Production Plan. Mock providers reuse the same table so cost behaviour in
demo mode matches production shape.

`app/providers/catalog.py` is now the source of truth for per-model pricing
(`ModelSpec.cost_per_unit` + `cost_unit`). `MODEL_PRICING` below is kept only
as an explicit override layer — add an entry there when a price needs to
diverge from the catalog without a catalog.py change — and every function in
this module keeps its historical signature and flat "USD per unit" behaviour
so existing callers (`services/storyboards.py`, `services/analysis.py`,
`services/voices.py`, `providers/model_router.py`) are unaffected.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.core.config import settings
from app.core.enums import ProductionMethod
from app.providers import catalog


class IntegrationBudgetExceeded(ValueError):
    """Raised by `guard_integration_spend` when a connectivity test would cost too much."""


#: Explicit overrides on top of the catalog-derived price table. Empty by
#: default — the catalog is authoritative. Add an entry here only to
#: deliberately diverge from it (e.g. a temporary negotiated rate) without
#: touching catalog.py.
MODEL_PRICING: Dict[str, float] = {}

#: Baseline per-scene estimate by production method (USD), 3-4s scene. These
#: are not per-model — they cover the zero/near-zero-cost local production
#: methods (`model_router.LOCAL_METHODS`) that never touch a provider.
METHOD_BASE_COST: Dict[str, float] = {
    ProductionMethod.ORIGINAL_VIDEO.value: 0.00,
    ProductionMethod.ORIGINAL_PHOTO.value: 0.00,
    ProductionMethod.PHOTO_MOTION.value: 0.02,
    ProductionMethod.MOTION_GRAPHICS.value: 0.01,
    ProductionMethod.AI_IMAGE.value: 0.06,
    ProductionMethod.AI_VIDEO.value: 0.55,
}

#: Non-scene line items not tied to a specific model.
FLAT_COSTS = {
    "voice_per_1k_chars": 0.18,
    "music_track": 0.20,
    "caption_render": 0.0,
    "final_render": 0.0,
    "qc_check": 0.0,
}


def _catalog_price_table() -> Dict[str, float]:
    """Model id -> cost_per_unit, keyed by both the seeded id and whatever
    id an operator has configured via settings, so a caller using either
    still resolves to the same price."""
    table: Dict[str, float] = {}
    for spec in catalog.all_specs():
        table[spec.model_id] = spec.cost_per_unit
        table[catalog.configured_model_id(spec)] = spec.cost_per_unit
    return table


def _price_table() -> Dict[str, float]:
    table = _catalog_price_table()
    table.update(MODEL_PRICING)  # explicit overrides win
    return table


def price_for_model(model: str, units: float = 1.0) -> float:
    return round(_price_table().get(model, 0.05) * units, 4)


def price_with_units(model: str, units: float, unit: Optional[str] = None) -> float:
    """Price `units` of `model`'s cost basis.

    `unit` is accepted for callers that want to assert which cost_unit they
    expect to be paying against (it does not change the arithmetic — prices
    are already expressed per that model's own `cost_unit` in the catalog);
    a mismatch is not fatal, since an operator override in `MODEL_PRICING`
    may legitimately reprice a model without changing its unit semantics.
    """
    if unit is not None:
        spec = next((s for s in catalog.all_specs() if catalog.configured_model_id(s) == model or s.model_id == model), None)
        if spec is not None and spec.cost_unit != unit:
            raise ValueError(f"model '{model}' is priced per '{spec.cost_unit}', not '{unit}'")
    return price_for_model(model, units)


def estimate_scene_cost(method: str, duration_sec: float = 3.5, model: str | None = None) -> float:
    """Estimate the cost of producing one scene."""
    base = METHOD_BASE_COST.get(method, 0.05)
    if method == ProductionMethod.AI_VIDEO.value:
        per_sec = _price_table().get(model or "veo-3.1-fast-generate-preview", 0.15)
        return round(per_sec * max(duration_sec, 2.0), 4)
    if method == ProductionMethod.AI_IMAGE.value and model:
        return round(_price_table().get(model, base), 4)
    return round(base, 4)


def estimate_voice_cost(char_count: int, model: str = "eleven_v3") -> float:
    per_1k = _price_table().get(model, FLAT_COSTS["voice_per_1k_chars"])
    return round(per_1k * max(char_count, 1) / 1000.0, 4)


def describe_pricing() -> Dict[str, Any]:
    """Full pricing picture for the Settings → Providers UI. No secrets."""
    table = _price_table()
    by_kind: Dict[str, Any] = {}
    for kind in catalog.KINDS:
        specs = catalog.specs_for_kind(kind)
        if not specs:
            continue
        by_kind[kind] = [
            {
                "provider_id": s.provider_id,
                "model_id": catalog.configured_model_id(s),
                "display_name": s.display_name,
                "cost_unit": s.cost_unit,
                "cost_per_unit": table.get(catalog.configured_model_id(s), s.cost_per_unit),
                "quality_tier": s.quality_tier,
                "enabled": s.enabled,
            }
            for s in specs
        ]
    return {"by_kind": by_kind, "method_base_cost": dict(METHOD_BASE_COST), "flat_costs": dict(FLAT_COSTS)}


def integration_test_budget() -> float:
    return settings.INTEGRATION_TEST_BUDGET_USD


def guard_integration_spend(estimated_usd: float) -> None:
    """Refuse a one-off provider connectivity test above the integration cap.

    Separate from the per-project Budget Guard (`services/costs.py`) — this
    exists so a "test connection" action (Director Mode, or an adapter's own
    health check) can never spend real money beyond a small, fixed ceiling,
    even before a project or its own budget exists.
    """
    cap = integration_test_budget()
    if estimated_usd > cap:
        raise IntegrationBudgetExceeded(
            f"Refusing to run a provider connectivity test estimated at ${estimated_usd:.4f} — "
            f"exceeds INTEGRATION_TEST_BUDGET_USD (${cap:.2f})."
        )
