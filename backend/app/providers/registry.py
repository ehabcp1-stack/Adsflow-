"""Provider registry — resolves a capability to a concrete adapter.

Resolution order: explicit request → configured real adapter (key present and
FORCE_MOCK_PROVIDERS=false) → Mock adapter. The product is always usable.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.providers import adapters as A
from app.providers import catalog
from app.providers import mock as M
from app.providers.base import BaseProvider

_REGISTRY: Dict[str, Dict[str, BaseProvider]] = {
    "llm": {
        "mock": M.MockLLMProvider(),
        # Anthropic first: it is the writer for Iraqi Arabic, and `get_provider`
        # picks the first available non-mock adapter when none is named.
        "anthropic": A.AnthropicLLMAdapter(),
        "openai": A.OpenAILLMAdapter(),
        "gemini": A.GeminiLLMAdapter(),
    },
    "image": {
        "mock": M.MockImageProvider(),
        "openai": A.OpenAIImageAdapter(),
        "gemini": A.GeminiImageAdapter(),
    },
    "video": {
        "mock": M.MockVideoProvider(),
        "veo": A.VeoVideoAdapter(),
        "runway": A.RunwayVideoAdapter(),
        "seedance": A.SeedanceVideoAdapter(),
    },
    "voice": {
        "mock": M.MockVoiceProvider(),
        "elevenlabs": A.ElevenLabsVoiceAdapter(),
    },
    "music": {
        "mock": M.MockMusicProvider(),
        "music": A.GenericMusicAdapter(),
    },
}


def get_provider(kind: str, name: Optional[str] = None) -> BaseProvider:
    bucket = _REGISTRY[kind]
    if name and name in bucket and bucket[name].available():
        return bucket[name]
    if not settings.FORCE_MOCK_PROVIDERS:
        for key, provider in bucket.items():
            if key != "mock" and provider.available():
                return provider
    return bucket["mock"]


def get_llm(name: Optional[str] = None) -> M.MockLLMProvider:
    return get_provider("llm", name)  # type: ignore[return-value]


def get_image(name: Optional[str] = None):
    return get_provider("image", name)


def get_video(name: Optional[str] = None):
    return get_provider("video", name)


def get_voice(name: Optional[str] = None):
    return get_provider("voice", name)


def get_music(name: Optional[str] = None):
    return get_provider("music", name)


def provider_status() -> List[Dict[str, Any]]:
    """Powers the Settings → Providers screen.

    Every original key stays exactly as before (existing callers —
    `app/api/library.py`, `tests/test_providers.py` — read these by name);
    catalog metadata and in-process health are merged in as additional keys.
    """
    health = catalog.health_snapshot()
    out: List[Dict[str, Any]] = []
    for kind, bucket in _REGISTRY.items():
        for name, provider in bucket.items():
            cap = provider.capability()
            provider_specs = [s for s in catalog.specs_for_kind(kind) if s.provider_id == name]
            provider_health = health.get(name, {})
            out.append(
                {
                    "kind": kind,
                    "name": name,
                    "models": cap.models,
                    "is_mock": cap.is_mock,
                    "requires_key": cap.requires_key,
                    "key_present": bool(getattr(settings, cap.requires_key, None)) if cap.requires_key else True,
                    "available": provider.available(),
                    "active": get_provider(kind).capability().name == name,
                    "notes": cap.notes,
                    # -- catalog / health additions --
                    "quality_tiers": sorted({s.quality_tier for s in provider_specs}),
                    "fallback_priority": min((s.fallback_priority for s in provider_specs), default=None),
                    "healthy": provider_health.get("available", cap.is_mock),
                    "last_error": provider_health.get("last_error"),
                }
            )
    return out


def registry_snapshot() -> Dict[str, Any]:
    """Full provider/model catalog for the Settings → Providers UI.

    Grouped by kind, one row per provider with its models' full metadata,
    configured/healthy state and fallback ordering. No secret ever appears
    here — only settings *names* (e.g. "OPENAI_API_KEY") and booleans about
    whether a key is present, never a key's value.
    """
    health = catalog.health_snapshot()
    by_kind: Dict[str, List[Dict[str, Any]]] = {}
    for kind in catalog.KINDS:
        specs = catalog.specs_for_kind(kind)
        if not specs:
            continue
        active_name = get_provider(kind).capability().name if kind in _REGISTRY else None
        grouped: Dict[str, List[catalog.ModelSpec]] = {}
        for s in specs:
            grouped.setdefault(s.provider_id, []).append(s)

        rows: List[Dict[str, Any]] = []
        for provider_id, provider_specs in grouped.items():
            provider_specs = sorted(provider_specs, key=lambda s: (s.fallback_priority, s.model_id))
            provider_health = health.get(provider_id, {})
            rows.append(
                {
                    "provider_id": provider_id,
                    "is_default": provider_id == active_name,
                    "configured": provider_health.get("configured", provider_id == "mock"),
                    "key_present": provider_health.get("key_present", True),
                    "healthy": provider_health.get("available", provider_id == "mock"),
                    "last_error": provider_health.get("last_error"),
                    "models": [_model_snapshot(s) for s in provider_specs],
                }
            )
        rows.sort(key=lambda r: (r["provider_id"] != "mock", min((m["fallback_priority"] for m in r["models"]), default=999)))
        by_kind[kind] = rows
    return {"force_mock": settings.FORCE_MOCK_PROVIDERS, "by_kind": by_kind}


def _model_snapshot(s: catalog.ModelSpec) -> Dict[str, Any]:
    return {
        "model_id": catalog.configured_model_id(s),
        "seeded_model_id": s.model_id,
        "display_name": s.display_name,
        "capabilities": sorted(s.capabilities),
        "input_types": list(s.input_types),
        "output_types": list(s.output_types),
        "supported_resolutions": list(s.supported_resolutions),
        "supported_durations": list(s.supported_durations) if s.supported_durations else None,
        "supports_reference_image": s.supports_reference_image,
        "supports_image_to_video": s.supports_image_to_video,
        "supports_first_last_frame": s.supports_first_last_frame,
        "generates_audio": s.generates_audio,
        "max_inputs": s.max_inputs,
        "cost_unit": s.cost_unit,
        "cost_per_unit": s.cost_per_unit,
        "quality_tier": s.quality_tier,
        "latency_tier": s.latency_tier,
        "fidelity_score": s.fidelity_score,
        "enabled": s.enabled,
        "selectable": s.selectable,
        "fallback_priority": s.fallback_priority,
        "requires_key": s.requires_key,
        # Provenance — an operator has to be able to see, without reading the
        # source, whether a model id was ever checked against the vendor.
        "docs_url": s.docs_url,
        "verified_at": s.verified_at,
        "deprecated": s.deprecated,
        "sunset_date": s.sunset_date,
        "notes_ar": s.notes_ar,
        "notes_en": s.notes_en,
    }
