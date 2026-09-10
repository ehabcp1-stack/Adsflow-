"""Adapter placeholders for real providers.

Each class documents exactly what has to be filled in to go live. Until an
API key exists the registry keeps serving the Mock adapter, so the product
never breaks. Adding a provider must NOT require touching domain services.

    1. implement the adapter methods below (HTTP call + response mapping)
    2. add its models to app/providers/pricing.MODEL_PRICING
    3. list it in app/providers/model_router.MODEL_CANDIDATES
    4. set the API key in .env and FORCE_MOCK_PROVIDERS=false
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.providers.base import (
    ImageProvider,
    LLMProvider,
    MusicProvider,
    ProviderCapability,
    ProviderResult,
    VideoProvider,
    VoiceProvider,
)


class NotImplementedAdapterMixin:
    """Shared 'not wired yet' behaviour — never raises into the UI."""

    name = "unwired"
    key_setting: str = ""

    def available(self) -> bool:
        return bool(getattr(settings, self.key_setting, None)) and not settings.FORCE_MOCK_PROVIDERS

    def _unavailable(self, operation: str) -> ProviderResult:
        return ProviderResult(
            ok=False,
            provider=self.name,
            model="unconfigured",
            operation=operation,
            is_mock=False,
            error=(
                f"Provider '{self.name}' is not configured. Set {self.key_setting} in .env "
                "and implement its adapter to enable it."
            ),
        )


class OpenAILLMAdapter(NotImplementedAdapterMixin, LLMProvider):
    name = "openai"
    key_setting = "OPENAI_API_KEY"

    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            name=self.name, kind="llm", models=["gpt-5", "gpt-5-mini"], requires_key=self.key_setting
        )

    def complete_json(self, *, task: str, context: Dict[str, Any], model: Optional[str] = None) -> ProviderResult:
        # TODO(real): POST /v1/responses with a JSON schema per task, then map
        # the parsed payload into the same shape MockLLMProvider returns.
        return self._unavailable(task)


class GeminiLLMAdapter(NotImplementedAdapterMixin, LLMProvider):
    name = "gemini"
    key_setting = "GEMINI_API_KEY"

    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            name=self.name, kind="llm", models=["gemini-2.5-pro"], requires_key=self.key_setting
        )

    def complete_json(self, *, task: str, context: Dict[str, Any], model: Optional[str] = None) -> ProviderResult:
        return self._unavailable(task)


class OpenAIImageAdapter(NotImplementedAdapterMixin, ImageProvider):
    name = "openai"
    key_setting = "OPENAI_API_KEY"

    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            name=self.name, kind="image", models=["gpt-image-1"],
            requires_key=self.key_setting, supports_reference_image=True,
        )

    def generate_image(self, **kwargs: Any) -> ProviderResult:
        return self._unavailable("image_generation")


class GeminiImageAdapter(NotImplementedAdapterMixin, ImageProvider):
    name = "gemini"
    key_setting = "GEMINI_API_KEY"

    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            name=self.name, kind="image", models=["gemini-image", "seedream-4"],
            requires_key=self.key_setting, supports_reference_image=True,
        )

    def generate_image(self, **kwargs: Any) -> ProviderResult:
        return self._unavailable("image_generation")


class VeoVideoAdapter(NotImplementedAdapterMixin, VideoProvider):
    name = "veo"
    key_setting = "VEO_API_KEY"

    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            name=self.name, kind="video", models=["veo-3", "veo-3-fast"],
            requires_key=self.key_setting, supports_image_to_video=True, max_duration_sec=8.0,
        )

    def generate_video(self, **kwargs: Any) -> ProviderResult:
        return self._unavailable("video_generation")


class RunwayVideoAdapter(NotImplementedAdapterMixin, VideoProvider):
    name = "runway"
    key_setting = "RUNWAY_API_KEY"

    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            name=self.name, kind="video", models=["runway-gen4-turbo"],
            requires_key=self.key_setting, supports_image_to_video=True, max_duration_sec=10.0,
        )

    def generate_video(self, **kwargs: Any) -> ProviderResult:
        return self._unavailable("video_generation")


class SeedanceVideoAdapter(NotImplementedAdapterMixin, VideoProvider):
    name = "seedance"
    key_setting = "SEEDANCE_API_KEY"

    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            name=self.name, kind="video", models=["seedance-1-pro"],
            requires_key=self.key_setting, supports_image_to_video=True, max_duration_sec=10.0,
        )

    def generate_video(self, **kwargs: Any) -> ProviderResult:
        return self._unavailable("video_generation")


class ElevenLabsVoiceAdapter(NotImplementedAdapterMixin, VoiceProvider):
    name = "elevenlabs"
    key_setting = "ELEVENLABS_API_KEY"

    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            name=self.name, kind="voice",
            models=["eleven-multilingual-v2", "eleven-turbo-v2-5"], requires_key=self.key_setting,
        )

    def list_voices(self) -> List[Dict[str, Any]]:
        return []

    def synthesize(self, **kwargs: Any) -> ProviderResult:
        return self._unavailable("voice_generation")


class GenericMusicAdapter(NotImplementedAdapterMixin, MusicProvider):
    name = "music"
    key_setting = "MUSIC_API_KEY"

    def capability(self) -> ProviderCapability:
        return ProviderCapability(name=self.name, kind="music", models=["music-gen-pro"], requires_key=self.key_setting)

    def generate_music(self, **kwargs: Any) -> ProviderResult:
        return self._unavailable("music_generation")
