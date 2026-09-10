"""Provider abstraction.

CORE RULE: never couple domain logic to a single AI vendor. Everything the
product needs from an external model is expressed through these interfaces.
Adding a real vendor = writing one adapter + registering it. Nothing else.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# --------------------------------------------------------------------------
# Result envelopes
# --------------------------------------------------------------------------
@dataclass
class ProviderResult:
    ok: bool
    provider: str
    model: str
    operation: str
    is_mock: bool
    cost_usd: float = 0.0
    latency_ms: int = 0
    url: Optional[str] = None
    text: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    quality_hint: Optional[float] = None


@dataclass
class ProviderCapability:
    name: str
    kind: str  # llm | image | video | voice | music
    models: List[str]
    requires_key: Optional[str] = None
    is_mock: bool = False
    supports_reference_image: bool = False
    supports_image_to_video: bool = False
    max_duration_sec: float = 8.0
    notes: str = ""


class BaseProvider(abc.ABC):
    kind: str = "base"
    name: str = "base"
    is_mock: bool = False

    @abc.abstractmethod
    def capability(self) -> ProviderCapability: ...

    def available(self) -> bool:
        return True


class LLMProvider(BaseProvider):
    kind = "llm"

    @abc.abstractmethod
    def complete_json(
        self, *, task: str, context: Dict[str, Any], model: Optional[str] = None
    ) -> ProviderResult:
        """Return structured JSON for a named creative task."""


class ImageProvider(BaseProvider):
    kind = "image"

    @abc.abstractmethod
    def generate_image(
        self,
        *,
        prompt: Dict[str, Any],
        model: Optional[str] = None,
        reference_urls: Optional[List[str]] = None,
        aspect_ratio: str = "9:16",
    ) -> ProviderResult: ...


class VideoProvider(BaseProvider):
    kind = "video"

    @abc.abstractmethod
    def generate_video(
        self,
        *,
        prompt: Dict[str, Any],
        model: Optional[str] = None,
        keyframe_url: Optional[str] = None,
        duration_sec: float = 4.0,
        aspect_ratio: str = "9:16",
    ) -> ProviderResult: ...


class VoiceProvider(BaseProvider):
    kind = "voice"

    @abc.abstractmethod
    def synthesize(
        self,
        *,
        text: str,
        voice_id: str,
        model: Optional[str] = None,
        speed: float = 1.0,
        energy: float = 0.6,
        emotion: float = 0.5,
    ) -> ProviderResult: ...

    @abc.abstractmethod
    def list_voices(self) -> List[Dict[str, Any]]: ...


class MusicProvider(BaseProvider):
    kind = "music"

    @abc.abstractmethod
    def generate_music(
        self, *, brief: Dict[str, Any], duration_sec: float = 30.0, model: Optional[str] = None
    ) -> ProviderResult: ...
