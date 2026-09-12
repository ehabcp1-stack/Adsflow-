"""System status — provider/model catalogue, pricing and runtime health.

Powers Settings → Providers. Everything here is *describing* configuration,
never exposing it: the only credential-related values that leave this module
are the **name** of the settings variable a model needs (e.g. "OPENAI_API_KEY")
and booleans saying whether it is set. A key's value never appears in any
response — `tests/test_system_api.py` asserts that.
"""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from app.core.config import settings
from app.core.security import get_current_user
from app.media.ffmpeg import ffmpeg_available, ffprobe_available
from app.models import User
from app.providers.pricing import describe_pricing
from app.providers.registry import registry_snapshot

router = APIRouter(prefix="/system", tags=["system"])

#: Capability groups shown in the UI, in display order. `catalog.KINDS` also
#: contains "vision", which has no seeded models yet — a kind with no rows is
#: simply absent from `by_kind`, so the UI never renders an empty group.
KIND_ORDER = ("llm", "image", "video", "voice", "music")


def _flatten(snapshot: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """One row per (provider, model) pair, grouped by capability kind.

    `registry_snapshot()` nests models under their provider; the Providers
    screen lists models, so flatten here rather than in the browser — the
    provider-level flags (configured / healthy / default) are copied onto
    each of its models.
    """
    by_kind: Dict[str, List[Dict[str, Any]]] = {}
    for kind, providers in snapshot.get("by_kind", {}).items():
        rows: List[Dict[str, Any]] = []
        for provider in providers:
            provider_id = provider["provider_id"]
            for model in provider["models"]:
                rows.append(
                    {
                        "kind": kind,
                        "provider": provider_id,
                        "model_id": model["model_id"],
                        "display_name": model["display_name"],
                        "configured": bool(provider["configured"] and provider["key_present"]),
                        "key_present": bool(provider["key_present"]),
                        # Setting *name* only — never the value it holds.
                        "requires_key": model["requires_key"],
                        "enabled": bool(model["enabled"]),
                        "healthy": bool(provider["healthy"]),
                        "last_error": provider["last_error"],
                        "is_mock": provider_id == "mock",
                        "is_default": bool(provider["is_default"]),
                        "fallback_priority": model["fallback_priority"],
                        "quality_tier": model["quality_tier"],
                        "latency_tier": model["latency_tier"],
                        "cost_unit": model["cost_unit"],
                        "cost_per_unit": model["cost_per_unit"],
                        "capabilities": model["capabilities"],
                        "supports_reference_image": model["supports_reference_image"],
                        "supports_image_to_video": model["supports_image_to_video"],
                        # Provenance: whether this model id was ever checked
                        # against the vendor's own docs, and where.
                        "docs_url": model["docs_url"],
                        "verified_at": model["verified_at"],
                        "deprecated": model["deprecated"],
                        "sunset_date": model["sunset_date"],
                        "notes_ar": model["notes_ar"],
                        "notes_en": model["notes_en"],
                    }
                )
        rows.sort(key=lambda r: (r["fallback_priority"], r["model_id"]))
        by_kind[kind] = rows
    return by_kind


@router.get("/providers")
def system_providers(user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Every provider/model the product knows about, grouped by capability."""
    snapshot = registry_snapshot()
    by_kind = _flatten(snapshot)
    rows = [row for kind in by_kind for row in by_kind[kind]]
    return {
        "force_mock": snapshot["force_mock"],
        "runtime_mode": "mock" if settings.FORCE_MOCK_PROVIDERS else "real",
        "kinds": [kind for kind in KIND_ORDER if kind in by_kind],
        "by_kind": by_kind,
        "totals": {
            "models": len(rows),
            "configured": sum(1 for r in rows if r["configured"] and not r["is_mock"]),
            "healthy": sum(1 for r in rows if r["healthy"]),
            "mock": sum(1 for r in rows if r["is_mock"]),
        },
    }


@router.get("/pricing")
def system_pricing(user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Per-model prices plus the per-method and flat cost baselines."""
    return describe_pricing()


@router.get("/health")
def system_health(user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Runtime facts the Settings screen states honestly instead of implying."""
    return {
        "app": settings.APP_NAME,
        "parent_brand": settings.APP_BRAND_PARENT,
        "env": settings.ENV,
        "runtime_mode": "mock" if settings.FORCE_MOCK_PROVIDERS else "real",
        "force_mock_providers": settings.FORCE_MOCK_PROVIDERS,
        "storage_backend": settings.STORAGE_BACKEND,
        "job_backend": settings.JOB_BACKEND,
        "local_render_enabled": bool(settings.ENABLE_LOCAL_RENDER),
        "ffmpeg_available": ffmpeg_available(),
        "ffprobe_available": ffprobe_available(),
    }
