"""Cost model.

Prices are per-operation USD estimates used by the Budget Guard and the
Production Plan. Mock providers reuse the same table so cost behaviour in
demo mode matches production shape.
"""
from __future__ import annotations

from typing import Dict

from app.core.enums import ProductionMethod

#: USD per generated unit.
MODEL_PRICING: Dict[str, float] = {
    # LLM (per structured call, rough)
    "mock-llm-v1": 0.0,
    "gpt-5-mini": 0.01,
    "gpt-5": 0.05,
    "gemini-2.5-pro": 0.02,
    # Image (per image)
    "mock-image-v1": 0.0,
    "gpt-image-1": 0.04,
    "gemini-image": 0.03,
    "seedream-4": 0.03,
    # Video (per second of output)
    "mock-video-v1": 0.0,
    "veo-3-fast": 0.15,
    "veo-3": 0.40,
    "runway-gen4-turbo": 0.10,
    "seedance-1-pro": 0.08,
    # Voice (per 1k characters)
    "mock-voice-v1": 0.0,
    "eleven-multilingual-v2": 0.18,
    "eleven-turbo-v2-5": 0.09,
    # Music (per track)
    "mock-music-v1": 0.0,
    "music-gen-pro": 0.20,
}

#: Baseline per-scene estimate by production method (USD), 3-4s scene.
METHOD_BASE_COST: Dict[str, float] = {
    ProductionMethod.ORIGINAL_VIDEO.value: 0.00,
    ProductionMethod.ORIGINAL_PHOTO.value: 0.00,
    ProductionMethod.PHOTO_MOTION.value: 0.02,
    ProductionMethod.MOTION_GRAPHICS.value: 0.01,
    ProductionMethod.AI_IMAGE.value: 0.06,
    ProductionMethod.AI_VIDEO.value: 0.55,
}

#: Non-scene line items.
FLAT_COSTS = {
    "voice_per_1k_chars": 0.18,
    "music_track": 0.20,
    "caption_render": 0.0,
    "final_render": 0.0,
    "qc_check": 0.0,
}


def price_for_model(model: str, units: float = 1.0) -> float:
    return round(MODEL_PRICING.get(model, 0.05) * units, 4)


def estimate_scene_cost(method: str, duration_sec: float = 3.5, model: str | None = None) -> float:
    """Estimate the cost of producing one scene."""
    base = METHOD_BASE_COST.get(method, 0.05)
    if method == ProductionMethod.AI_VIDEO.value:
        per_sec = MODEL_PRICING.get(model or "veo-3-fast", 0.15)
        return round(per_sec * max(duration_sec, 2.0), 4)
    if method == ProductionMethod.AI_IMAGE.value and model:
        return round(MODEL_PRICING.get(model, base), 4)
    return round(base, 4)


def estimate_voice_cost(char_count: int, model: str = "eleven-multilingual-v2") -> float:
    per_1k = MODEL_PRICING.get(model, FLAT_COSTS["voice_per_1k_chars"])
    return round(per_1k * max(char_count, 1) / 1000.0, 4)
