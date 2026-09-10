"""Provider registry — resolves a capability to a concrete adapter.

Resolution order: explicit request → configured real adapter (key present and
FORCE_MOCK_PROVIDERS=false) → Mock adapter. The product is always usable.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.providers import adapters as A
from app.providers import mock as M
from app.providers.base import BaseProvider

_REGISTRY: Dict[str, Dict[str, BaseProvider]] = {
    "llm": {
        "mock": M.MockLLMProvider(),
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
    """Powers the Settings → Providers screen."""
    out: List[Dict[str, Any]] = []
    for kind, bucket in _REGISTRY.items():
        for name, provider in bucket.items():
            cap = provider.capability()
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
                }
            )
    return out
