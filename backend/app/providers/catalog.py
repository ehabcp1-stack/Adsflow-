"""Provider / model capability registry — the single source of truth.

Every place in the product that needs to know "what models exist, what can
they do, what do they cost, which setting configures them" reads this module
instead of hard-coding another list. `registry.py` resolves *which adapter
instance* serves a request; this module describes *what that adapter's
models are capable of* so routing, pricing and the Settings → Providers UI
share one definition instead of drifting apart.

IMPORTANT — model IDs here are configuration, not fact. This environment has
no network access to vendor documentation and no live API keys, so the
seeded `model_id` values below are simply the identifiers this product has
already been using (see the historical `MODEL_CANDIDATES` table in
`model_router.py` and `MODEL_PRICING` in `pricing.py`). They may be stale by
the time this code runs for real. `configured_model_id()` lets an operator
override any of them via a settings variable (documented per spec below)
without touching code — always prefer that path over editing this file, and
always confirm the value against the vendor's current docs before flipping
`FORCE_MOCK_PROVIDERS` off.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from app.core.config import settings

logger = logging.getLogger(__name__)

#: Valid ModelSpec.kind values.
KINDS = ("llm", "image", "video", "voice", "music", "vision")

#: Valid ModelSpec.cost_unit values — pricing.py knows how to price each one.
COST_UNITS = (
    "per_second",
    "per_image",
    "per_1k_input_tokens",
    "per_1k_output_tokens",
    "per_1k_chars",
    "per_minute",
    "per_request",
)

#: Valid ModelSpec.quality_tier values, worst to best (used for sort order).
QUALITY_TIERS = ("economy", "standard", "premium", "flagship")

#: Valid ModelSpec.latency_tier values.
LATENCY_TIERS = ("fast", "standard", "slow")


@dataclass(frozen=True)
class ModelSpec:
    """Capability + cost metadata for exactly one (provider, model) pair."""

    provider_id: str
    model_id: str
    kind: str
    display_name: str
    capabilities: FrozenSet[str] = field(default_factory=frozenset)
    input_types: Tuple[str, ...] = ()
    output_types: Tuple[str, ...] = ()
    supported_resolutions: Tuple[str, ...] = ()
    #: (min_seconds, max_seconds) for video/voice/music generations; None for llm/image.
    supported_durations: Optional[Tuple[float, float]] = None
    supports_reference_image: bool = False
    supports_image_to_video: bool = False
    supports_first_last_frame: bool = False
    generates_audio: bool = False
    max_inputs: int = 1
    cost_unit: str = "per_request"
    cost_per_unit: float = 0.0
    quality_tier: str = "standard"
    latency_tier: str = "standard"
    fidelity_score: float = 0.8
    enabled: bool = True
    fallback_priority: int = 100
    #: Settings attribute holding the API key, or None for the mock provider.
    requires_key: Optional[str] = None
    #: Settings attribute that can override `model_id` for this spec.
    model_id_setting: Optional[str] = None
    notes_ar: str = ""
    notes_en: str = ""

    @property
    def key(self) -> Tuple[str, str]:
        return (self.provider_id, self.model_id)


def configured_model_id(spec: ModelSpec) -> str:
    """Resolve the model id actually used at call time.

    Always prefers an operator-set settings override over the seeded
    default — see the module docstring for why the default cannot be
    trusted as current.
    """
    if spec.model_id_setting:
        override = getattr(settings, spec.model_id_setting, None)
        if override:
            return override
    return spec.model_id


# --------------------------------------------------------------------------
# Seed data
# --------------------------------------------------------------------------
_SPECS: List[ModelSpec] = [
    # -- LLM ---------------------------------------------------------------
    ModelSpec(
        provider_id="mock", model_id="mock-llm-v1", kind="llm",
        display_name="Mock LLM (demo)",
        capabilities=frozenset({"structured_json"}),
        input_types=("text",), output_types=("json",),
        cost_unit="per_request", cost_per_unit=0.0,
        quality_tier="standard", latency_tier="fast", fidelity_score=0.6,
        fallback_priority=999, requires_key=None,
        notes_ar="مزود تجريبي بدون كلفة — لا يحتاج مفتاح.",
        notes_en="Demo provider, always available, zero cost.",
    ),
    ModelSpec(
        provider_id="openai", model_id="gpt-5-mini", kind="llm",
        display_name="OpenAI GPT-5 mini",
        capabilities=frozenset({"structured_json", "json_mode"}),
        input_types=("text",), output_types=("json",),
        cost_unit="per_request", cost_per_unit=0.01,
        quality_tier="standard", latency_tier="fast", fidelity_score=0.85,
        fallback_priority=10, requires_key="OPENAI_API_KEY", model_id_setting="OPENAI_LLM_MODEL",
        notes_ar="نموذج نصي اقتصادي وسريع للمهام البنيوية.",
        notes_en="Fast, economical text model for structured tasks. Confirm id against OpenAI's current model list.",
    ),
    ModelSpec(
        provider_id="openai", model_id="gpt-5", kind="llm",
        display_name="OpenAI GPT-5",
        capabilities=frozenset({"structured_json", "json_mode"}),
        input_types=("text",), output_types=("json",),
        cost_unit="per_request", cost_per_unit=0.05,
        quality_tier="flagship", latency_tier="standard", fidelity_score=0.95,
        fallback_priority=20, requires_key="OPENAI_API_KEY", model_id_setting="OPENAI_LLM_MODEL",
        notes_ar="أعلى جودة نصية متاحة، للمهام الحرجة (خطاف، مفهوم رئيسي).",
        notes_en="Highest-quality text tier for critical tasks. Confirm id against OpenAI's current model list.",
    ),
    ModelSpec(
        provider_id="gemini", model_id="gemini-2.5-pro", kind="llm",
        display_name="Gemini 2.5 Pro",
        capabilities=frozenset({"structured_json", "json_mode"}),
        input_types=("text",), output_types=("json",),
        cost_unit="per_request", cost_per_unit=0.02,
        quality_tier="premium", latency_tier="standard", fidelity_score=0.9,
        fallback_priority=15, requires_key="GEMINI_API_KEY", model_id_setting="GEMINI_LLM_MODEL",
        notes_ar="بديل جيد لنماذج OpenAI بجودة قريبة.",
        notes_en="Strong OpenAI alternative. Confirm id against Google's current Gemini model list.",
    ),
    # -- Image ---------------------------------------------------------------
    ModelSpec(
        provider_id="mock", model_id="mock-image-v1", kind="image",
        display_name="Mock Image (demo)",
        capabilities=frozenset({"text_to_image"}),
        input_types=("text",), output_types=("image",),
        supported_resolutions=("1080x1920",),
        cost_unit="per_image", cost_per_unit=0.0,
        quality_tier="standard", latency_tier="fast", fidelity_score=0.5,
        fallback_priority=999, requires_key=None,
        notes_ar="يولد إطارات SVG حقيقية بدون كلفة.",
        notes_en="Real SVG placeholder frames, zero cost, always available.",
    ),
    ModelSpec(
        provider_id="openai", model_id="gpt-image-1", kind="image",
        display_name="OpenAI GPT Image 1",
        capabilities=frozenset({"text_to_image", "reference_image"}),
        input_types=("text", "image"), output_types=("image",),
        supported_resolutions=("1024x1792", "1080x1920"),
        supports_reference_image=True, max_inputs=4,
        cost_unit="per_image", cost_per_unit=0.04,
        quality_tier="premium", latency_tier="standard", fidelity_score=0.9,
        fallback_priority=10, requires_key="OPENAI_API_KEY", model_id_setting="OPENAI_IMAGE_MODEL",
        notes_ar="جودة عالية مع دعم صور مرجعية لالتزام هوية المشروع.",
        notes_en="High fidelity, supports reference images for project-fidelity lock. Confirm id against OpenAI docs.",
    ),
    ModelSpec(
        provider_id="gemini", model_id="gemini-image", kind="image",
        display_name="Gemini Image",
        capabilities=frozenset({"text_to_image", "reference_image"}),
        input_types=("text", "image"), output_types=("image",),
        supported_resolutions=("1080x1920",),
        supports_reference_image=True, max_inputs=3,
        cost_unit="per_image", cost_per_unit=0.03,
        quality_tier="standard", latency_tier="fast", fidelity_score=0.82,
        fallback_priority=20, requires_key="GEMINI_API_KEY", model_id_setting="GEMINI_IMAGE_MODEL",
        notes_ar="بديل اقتصادي بجودة جيدة.",
        notes_en="Economical alternative. Confirm id against Google's current image model list.",
    ),
    ModelSpec(
        provider_id="gemini", model_id="seedream-4", kind="image",
        display_name="Seedream 4",
        capabilities=frozenset({"text_to_image", "reference_image"}),
        input_types=("text", "image"), output_types=("image",),
        supported_resolutions=("1080x1920",),
        supports_reference_image=True, max_inputs=2,
        cost_unit="per_image", cost_per_unit=0.03,
        quality_tier="economy", latency_tier="fast", fidelity_score=0.75,
        fallback_priority=5, requires_key="GEMINI_API_KEY", model_id_setting="GEMINI_IMAGE_MODEL",
        notes_ar="خيار اقتصادي أول للصور — يستخدم نفس مفتاح Gemini في هذا المنتج.",
        notes_en=(
            "Cheapest image candidate for economy quality level. Routed through the Gemini "
            "adapter/key in this product's existing model_router table — confirm whether the "
            "vendor is reached via Gemini's API surface or needs its own key/base URL."
        ),
    ),
    # -- Video ---------------------------------------------------------------
    ModelSpec(
        provider_id="mock", model_id="mock-video-v1", kind="video",
        display_name="Mock Video (demo)",
        capabilities=frozenset({"text_to_video", "image_to_video"}),
        input_types=("text", "image"), output_types=("video",),
        supported_resolutions=("1080x1920",), supported_durations=(2.0, 10.0),
        supports_image_to_video=True,
        cost_unit="per_second", cost_per_unit=0.0,
        quality_tier="standard", latency_tier="fast", fidelity_score=0.5,
        fallback_priority=999, requires_key=None,
        notes_ar="فيديو MP4 حقيقي قصير إذا FFmpeg موجود، وإلا بوستر SVG.",
        notes_en="Real short MP4 when FFmpeg is present, else an SVG poster. Zero cost.",
    ),
    ModelSpec(
        provider_id="veo", model_id="veo-3-fast", kind="video",
        display_name="Veo 3 Fast",
        capabilities=frozenset({"text_to_video", "image_to_video"}),
        input_types=("text", "image"), output_types=("video",),
        supported_resolutions=("1080x1920",), supported_durations=(2.0, 8.0),
        supports_image_to_video=True, generates_audio=True,
        cost_unit="per_second", cost_per_unit=0.15,
        quality_tier="standard", latency_tier="fast", fidelity_score=0.85,
        fallback_priority=10, requires_key="VEO_API_KEY", model_id_setting="VEO_VIDEO_MODEL",
        notes_ar="التوازن الافتراضي بين الجودة والكلفة للفيديو بالذكاء الاصطناعي.",
        notes_en="Default smart_premium video candidate. Confirm id against Google's current Veo docs.",
    ),
    ModelSpec(
        provider_id="veo", model_id="veo-3", kind="video",
        display_name="Veo 3",
        capabilities=frozenset({"text_to_video", "image_to_video"}),
        input_types=("text", "image"), output_types=("video",),
        supported_resolutions=("1080x1920",), supported_durations=(2.0, 8.0),
        supports_image_to_video=True, generates_audio=True,
        cost_unit="per_second", cost_per_unit=0.40,
        quality_tier="flagship", latency_tier="slow", fidelity_score=0.95,
        fallback_priority=20, requires_key="VEO_API_KEY", model_id_setting="VEO_VIDEO_MODEL",
        notes_ar="أعلى جودة فيديو، للقطات البطل/الخطاف فقط عند maximum_quality.",
        notes_en="Highest video quality, hook/hero scenes at maximum_quality only. Confirm id against Google docs.",
    ),
    ModelSpec(
        provider_id="runway", model_id="runway-gen4-turbo", kind="video",
        display_name="Runway Gen-4 Turbo",
        capabilities=frozenset({"text_to_video", "image_to_video"}),
        input_types=("text", "image"), output_types=("video",),
        supported_resolutions=("1080x1920",), supported_durations=(2.0, 10.0),
        supports_image_to_video=True, supports_first_last_frame=True,
        cost_unit="per_second", cost_per_unit=0.10,
        quality_tier="standard", latency_tier="standard", fidelity_score=0.8,
        fallback_priority=15, requires_key="RUNWAY_API_KEY", model_id_setting="RUNWAY_VIDEO_MODEL",
        notes_ar="بديل للفيديو مع دعم إطار أول/أخير.",
        notes_en="Video fallback, supports first/last frame control. Confirm id against Runway's current API docs.",
    ),
    ModelSpec(
        provider_id="seedance", model_id="seedance-1-pro", kind="video",
        display_name="Seedance 1 Pro",
        capabilities=frozenset({"text_to_video", "image_to_video"}),
        input_types=("text", "image"), output_types=("video",),
        supported_resolutions=("1080x1920",), supported_durations=(2.0, 10.0),
        supports_image_to_video=True,
        cost_unit="per_second", cost_per_unit=0.08,
        quality_tier="economy", latency_tier="standard", fidelity_score=0.75,
        fallback_priority=5, requires_key="SEEDANCE_API_KEY", model_id_setting="SEEDANCE_VIDEO_MODEL",
        notes_ar="خيار اقتصادي أول للفيديو.",
        notes_en="Cheapest video candidate for economy quality level. Confirm id and API host against current docs.",
    ),
    # -- Voice ---------------------------------------------------------------
    ModelSpec(
        provider_id="mock", model_id="mock-voice-v1", kind="voice",
        display_name="Mock Voice (demo)",
        capabilities=frozenset({"tts"}),
        input_types=("text",), output_types=("audio",),
        supported_durations=(0.5, 120.0),
        cost_unit="per_1k_chars", cost_per_unit=0.0,
        quality_tier="standard", latency_tier="fast", fidelity_score=0.5,
        fallback_priority=999, requires_key=None,
        notes_ar="مسار صوتي صامت بتوقيت حقيقي — عراقي تجريبي.",
        notes_en="Silent, correctly-timed audio track with demo Iraqi voice profiles.",
    ),
    ModelSpec(
        provider_id="elevenlabs", model_id="eleven-multilingual-v2", kind="voice",
        display_name="ElevenLabs Multilingual v2",
        capabilities=frozenset({"tts", "voice_cloning"}),
        input_types=("text",), output_types=("audio",),
        supported_durations=(0.5, 300.0),
        cost_unit="per_1k_chars", cost_per_unit=0.18,
        quality_tier="premium", latency_tier="standard", fidelity_score=0.9,
        fallback_priority=10, requires_key="ELEVENLABS_API_KEY", model_id_setting="ELEVENLABS_VOICE_MODEL",
        notes_ar="أفضل جودة صوتية عربية/عراقية متعددة اللغات.",
        notes_en="Best-quality multilingual voice, used for Iraqi VO. Confirm id against ElevenLabs' current docs.",
    ),
    ModelSpec(
        provider_id="elevenlabs", model_id="eleven-turbo-v2-5", kind="voice",
        display_name="ElevenLabs Turbo v2.5",
        capabilities=frozenset({"tts"}),
        input_types=("text",), output_types=("audio",),
        supported_durations=(0.5, 300.0),
        cost_unit="per_1k_chars", cost_per_unit=0.09,
        quality_tier="standard", latency_tier="fast", fidelity_score=0.8,
        fallback_priority=15, requires_key="ELEVENLABS_API_KEY", model_id_setting="ELEVENLABS_VOICE_MODEL",
        notes_ar="أسرع وأرخص، لمسودات أو مراجعات سريعة.",
        notes_en="Faster, cheaper — good for drafts. Confirm id against ElevenLabs' current docs.",
    ),
    # -- Music ---------------------------------------------------------------
    ModelSpec(
        provider_id="mock", model_id="mock-music-v1", kind="music",
        display_name="Mock Music (demo)",
        capabilities=frozenset({"text_to_music"}),
        input_types=("text",), output_types=("audio",),
        supported_durations=(5.0, 120.0),
        cost_unit="per_request", cost_per_unit=0.0,
        quality_tier="standard", latency_tier="fast", fidelity_score=0.4,
        fallback_priority=999, requires_key=None,
        notes_ar="مسار صامت بتوقيت حقيقي.",
        notes_en="Silent, correctly-timed audio track. Zero cost.",
    ),
    ModelSpec(
        provider_id="music", model_id="music-gen-pro", kind="music",
        display_name="Generic Music Generator",
        capabilities=frozenset({"text_to_music"}),
        input_types=("text",), output_types=("audio",),
        supported_durations=(5.0, 180.0),
        cost_unit="per_request", cost_per_unit=0.20,
        quality_tier="standard", latency_tier="slow", fidelity_score=0.7,
        fallback_priority=10, requires_key="MUSIC_API_KEY", model_id_setting="MUSIC_MODEL",
        notes_ar="لا يوجد مزود موسيقى محدد بعد — عنصر نائب قابل للتهيئة.",
        notes_en=(
            "No specific music vendor has been chosen by the product yet — this is a "
            "configurable placeholder. Set MUSIC_BASE_URL, MUSIC_MODEL and MUSIC_API_KEY to "
            "whatever vendor is selected, and rewrite GenericMusicAdapter's request shape to "
            "match that vendor's actual API before enabling it."
        ),
    ),
]

_BY_KEY: Dict[Tuple[str, str], ModelSpec] = {s.key: s for s in _SPECS}

_QUALITY_RANK = {tier: i for i, tier in enumerate(QUALITY_TIERS)}


def all_specs() -> List[ModelSpec]:
    return list(_SPECS)


def specs_for_kind(kind: str) -> List[ModelSpec]:
    return [s for s in _SPECS if s.kind == kind]


def spec(provider_id: str, model_id: str) -> Optional[ModelSpec]:
    return _BY_KEY.get((provider_id, model_id))


def candidates(
    kind: str,
    *,
    provider_id: Optional[str] = None,
    capability: Optional[str] = None,
    min_duration_sec: Optional[float] = None,
    max_duration_sec: Optional[float] = None,
    requires_reference_image: Optional[bool] = None,
    requires_image_to_video: Optional[bool] = None,
    include_disabled: bool = False,
) -> List[ModelSpec]:
    """Filter+sort candidate models for a job.

    Sort order: `fallback_priority` ascending (lower tried first), then
    `quality_tier` descending (best quality wins ties) — this mirrors the
    cost/quality trade-off `model_router.py` already encodes, but generalised
    so any future caller (Director Mode, auto-fix) can ask the same question.
    """
    out = [s for s in _SPECS if s.kind == kind]
    if not include_disabled:
        out = [s for s in out if s.enabled]
    if provider_id is not None:
        out = [s for s in out if s.provider_id == provider_id]
    if capability is not None:
        out = [s for s in out if capability in s.capabilities]
    if requires_reference_image:
        out = [s for s in out if s.supports_reference_image]
    if requires_image_to_video:
        out = [s for s in out if s.supports_image_to_video]
    if min_duration_sec is not None or max_duration_sec is not None:
        filtered = []
        for s in out:
            if s.supported_durations is None:
                continue
            lo, hi = s.supported_durations
            if min_duration_sec is not None and hi < min_duration_sec:
                continue
            if max_duration_sec is not None and lo > max_duration_sec:
                continue
            filtered.append(s)
        out = filtered
    out.sort(key=lambda s: (s.fallback_priority, -_QUALITY_RANK.get(s.quality_tier, 0)))
    return out


# --------------------------------------------------------------------------
# In-process health tracking — no DB, resets on process restart. Powers the
# Settings → Providers "healthy / unavailable" badge alongside static
# configuration (key present, enabled) which alone can't show a vendor that
# is configured but currently failing.
# --------------------------------------------------------------------------
_health_lock = threading.Lock()
_health: Dict[str, Dict[str, Any]] = {}


def record_success(provider: str) -> None:
    with _health_lock:
        entry = _health.setdefault(provider, {})
        entry["last_error"] = None
        entry["consecutive_failures"] = 0


def record_failure(provider: str, error: str) -> None:
    # Never let a raw error containing a key/token reach in-process state that
    # a status endpoint might surface. Adapters pass already-redacted text,
    # but redact defensively here too since this is the last line of defence
    # before it's exposed via health_snapshot().
    from app.providers.http import redact

    with _health_lock:
        entry = _health.setdefault(provider, {})
        entry["last_error"] = redact(str(error))[:500]
        entry["consecutive_failures"] = entry.get("consecutive_failures", 0) + 1
    logger.warning("provider '%s' reported a failure: %s", provider, redact(str(error))[:200])


def health_snapshot() -> Dict[str, Dict[str, Any]]:
    """Per-provider status for the Settings → Providers screen.

    `configured` = at least one enabled model exists for the provider.
    `key_present` = the required settings value is set (never its value).
    `available` = configured AND key present AND (mock, which ignores the
    force-mock flag by definition, OR not forced into mock mode) AND no
    in-process failure record without a later success.
    """
    providers = sorted({s.provider_id for s in _SPECS})
    out: Dict[str, Dict[str, Any]] = {}
    for provider_id in providers:
        provider_specs = [s for s in _SPECS if s.provider_id == provider_id]
        enabled = any(s.enabled for s in provider_specs)
        key_settings = {s.requires_key for s in provider_specs if s.requires_key}
        key_present = all(bool(getattr(settings, name, None)) for name in key_settings) if key_settings else True
        with _health_lock:
            health = dict(_health.get(provider_id, {}))
        healthy = health.get("consecutive_failures", 0) == 0
        ignores_force_mock = provider_id == "mock"
        out[provider_id] = {
            "configured": bool(provider_specs) and (not key_settings or key_present),
            "enabled": enabled,
            "key_present": key_present,
            "last_error": health.get("last_error"),
            "available": enabled and key_present and healthy and (ignores_force_mock or not settings.FORCE_MOCK_PROVIDERS),
        }
    return out
