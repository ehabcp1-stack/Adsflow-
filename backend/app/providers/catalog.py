"""Provider / model capability registry — the single source of truth.

Every place in the product that needs to know "what models exist, what can
they do, what do they cost, which setting configures them" reads this module
instead of hard-coding another list. `registry.py` resolves *which adapter
instance* serves a request; this module describes *what that adapter's
models are capable of* so routing, pricing and the Settings → Providers UI
share one definition instead of drifting apart.

IMPORTANT — model IDs here are configuration, not fact, and every spec says
which it is. `verified_at` carries the date the id was read from the vendor's
own documentation and `docs_url` says where; a spec with `verified_at=None`
has never been confirmed and the UI marks it as such. `configured_model_id()`
lets an operator override any id via a settings variable without touching
code — always prefer that path, and always re-check `docs_url` before
flipping `FORCE_MOCK_PROVIDERS` off, because vendors rename and retire models
faster than this file is edited.

`deprecated=True` means the vendor has announced the model is going away;
`candidates()` will not return it, so a retired model can never be selected
by the router by accident.
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
    #: The vendor's own documentation page for this model.
    docs_url: str = ""
    #: ISO date the model_id above was last read from `docs_url`. None means
    #: nobody has ever confirmed it — treat the id as a guess.
    verified_at: Optional[str] = None
    #: The vendor has announced this model is going away. Never routed to.
    deprecated: bool = False
    #: ISO date the vendor shuts the model off, when one has been announced.
    sunset_date: Optional[str] = None
    notes_ar: str = ""
    notes_en: str = ""

    @property
    def key(self) -> Tuple[str, str]:
        return (self.provider_id, self.model_id)

    @property
    def selectable(self) -> bool:
        """Can the router actually choose this model right now?"""
        return self.enabled and not self.deprecated


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
    # Copywriting is where Arabic quality is decided, so the default primary is
    # the best price/quality text model we can verify — not the cheapest.
    ModelSpec(
        provider_id="anthropic", model_id="claude-sonnet-5", kind="llm",
        display_name="Claude Sonnet 5",
        capabilities=frozenset({"structured_json", "json_mode", "long_context"}),
        input_types=("text", "image"), output_types=("json",),
        cost_unit="per_1k_input_tokens", cost_per_unit=0.002,
        quality_tier="premium", latency_tier="standard", fidelity_score=0.93,
        fallback_priority=10, requires_key="ANTHROPIC_API_KEY",
        model_id_setting="ANTHROPIC_LLM_MODEL",
        docs_url="https://platform.claude.com/docs/en/about-claude/models/overview",
        verified_at="2026-09-12",
        notes_ar="الكاتب الأساسي — أفضل نسبة جودة/سعر للنص العربي ($2 دخول / $10 خروج لكل مليون).",
        notes_en="Primary copywriter: best verified price/quality for Arabic ($2/$10 per MTok).",
    ),
    ModelSpec(
        provider_id="anthropic", model_id="claude-opus-5", kind="llm",
        display_name="Claude Opus 5",
        capabilities=frozenset({"structured_json", "json_mode", "long_context"}),
        input_types=("text", "image"), output_types=("json",),
        cost_unit="per_1k_input_tokens", cost_per_unit=0.005,
        quality_tier="flagship", latency_tier="slow", fidelity_score=0.97,
        fallback_priority=30, requires_key="ANTHROPIC_API_KEY",
        model_id_setting="ANTHROPIC_LLM_MODEL",
        docs_url="https://platform.claude.com/docs/en/about-claude/models/overview",
        verified_at="2026-09-12",
        notes_ar="للمراجعة النهائية للهجة العراقية فقط — نداء واحد بالإعلان، مو للكتابة كلها.",
        notes_en="Final Iraqi-dialect review only — one call per ad, never the bulk writing.",
    ),
    ModelSpec(
        provider_id="gemini", model_id="gemini-3.5-flash-lite", kind="llm",
        display_name="Gemini 3.5 Flash-Lite",
        capabilities=frozenset({"structured_json", "json_mode"}),
        input_types=("text",), output_types=("json",),
        cost_unit="per_1k_input_tokens", cost_per_unit=0.0003,
        quality_tier="economy", latency_tier="fast", fidelity_score=0.78,
        fallback_priority=5, requires_key="GEMINI_API_KEY", model_id_setting="GEMINI_LLM_MODEL",
        docs_url="https://ai.google.dev/gemini-api/docs/models",
        verified_at="2026-09-12",
        notes_ar="للمهام الرخيصة: التصنيف، الوسوم، أسماء الملفات ($0.30 لكل مليون دخول).",
        notes_en="Bulk cheap work: tagging, classification, file naming ($0.30/MTok in).",
    ),
    ModelSpec(
        provider_id="gemini", model_id="gemini-3.5-flash", kind="llm",
        display_name="Gemini 3.5 Flash",
        capabilities=frozenset({"structured_json", "json_mode"}),
        input_types=("text", "image"), output_types=("json",),
        cost_unit="per_1k_input_tokens", cost_per_unit=0.0015,
        quality_tier="standard", latency_tier="fast", fidelity_score=0.87,
        fallback_priority=20, requires_key="GEMINI_API_KEY", model_id_setting="GEMINI_LLM_MODEL",
        docs_url="https://ai.google.dev/gemini-api/docs/models",
        verified_at="2026-09-12",
        notes_ar="بديل احتياطي إذا مفتاح Anthropic غير متاح.",
        notes_en="Fallback writer when the Anthropic key is absent.",
    ),
    ModelSpec(
        provider_id="openai", model_id="(set OPENAI_LLM_MODEL)", kind="llm",
        display_name="OpenAI (not configured)",
        capabilities=frozenset({"structured_json", "json_mode"}),
        input_types=("text",), output_types=("json",),
        cost_unit="per_1k_input_tokens", cost_per_unit=0.0,
        quality_tier="standard", latency_tier="fast", fidelity_score=0.85,
        enabled=False,
        fallback_priority=900, requires_key="OPENAI_API_KEY", model_id_setting="OPENAI_LLM_MODEL",
        docs_url="https://platform.openai.com/docs/models",
        notes_ar="معطّل: ما تأكدنا من اسم موديل حالي. فعّله بعد ضبط OPENAI_LLM_MODEL من التوثيق الرسمي.",
        notes_en=(
            "Disabled on purpose: no current OpenAI text model id has been verified for this "
            "product. Set OPENAI_LLM_MODEL from the official model list, then enable."
        ),
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
    # The image tier matters more than it used to: hero-frame-first means an
    # approved still is what a paid video call is conditioned on, so a good
    # still is cheaper than a bad video.
    ModelSpec(
        provider_id="gemini", model_id="gemini-3-pro-image", kind="image",
        display_name="Gemini 3 Pro Image (Nano Banana Pro)",
        capabilities=frozenset({"text_to_image", "reference_image", "image_edit"}),
        input_types=("text", "image"), output_types=("image",),
        supported_resolutions=("1080x1920",),
        supports_reference_image=True, max_inputs=4,
        cost_unit="per_image", cost_per_unit=0.06,
        quality_tier="premium", latency_tier="standard", fidelity_score=0.92,
        fallback_priority=10, requires_key="GEMINI_API_KEY", model_id_setting="GEMINI_IMAGE_MODEL",
        docs_url="https://ai.google.dev/gemini-api/docs/models",
        verified_at="2026-09-12",
        notes_ar="إطار البطل: أعلى جودة صور مع تعديل صور العميل بدل اختراع مبانٍ.",
        notes_en="Hero frames: best image tier, edits the customer's own photo rather than inventing a building.",
    ),
    ModelSpec(
        provider_id="gemini", model_id="gemini-3.1-flash-image", kind="image",
        display_name="Gemini 3.1 Flash Image (Nano Banana 2)",
        capabilities=frozenset({"text_to_image", "reference_image", "image_edit"}),
        input_types=("text", "image"), output_types=("image",),
        supported_resolutions=("1080x1920",),
        supports_reference_image=True, max_inputs=3,
        cost_unit="per_image", cost_per_unit=0.03,
        quality_tier="standard", latency_tier="fast", fidelity_score=0.85,
        fallback_priority=20, requires_key="GEMINI_API_KEY", model_id_setting="GEMINI_IMAGE_MODEL",
        docs_url="https://ai.google.dev/gemini-api/docs/models",
        verified_at="2026-09-12",
        notes_ar="التوازن الافتراضي للصور.",
        notes_en="Default balanced image tier.",
    ),
    ModelSpec(
        provider_id="gemini", model_id="gemini-3.1-flash-lite-image", kind="image",
        display_name="Gemini 3.1 Flash-Lite Image (Nano Banana 2 Lite)",
        capabilities=frozenset({"text_to_image", "reference_image"}),
        input_types=("text", "image"), output_types=("image",),
        supported_resolutions=("1080x1920",),
        supports_reference_image=True, max_inputs=2,
        cost_unit="per_image", cost_per_unit=0.015,
        quality_tier="economy", latency_tier="fast", fidelity_score=0.76,
        fallback_priority=5, requires_key="GEMINI_API_KEY", model_id_setting="GEMINI_IMAGE_MODEL",
        docs_url="https://ai.google.dev/gemini-api/docs/models",
        verified_at="2026-09-12",
        notes_ar="مسودات الإطارات — رخيص، للعرض قبل الموافقة.",
        notes_en="Draft keyframes — cheap, shown before approval.",
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
        enabled=False,
        fallback_priority=900, requires_key="OPENAI_API_KEY", model_id_setting="OPENAI_IMAGE_MODEL",
        docs_url="https://platform.openai.com/docs/models",
        notes_ar="معطّل حتى يتأكد الاسم من التوثيق الرسمي.",
        notes_en="Disabled until the id is confirmed against OpenAI's current model list.",
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
    # Veo 3.1 replaced Veo 3 as the product's video spine because it ships
    # three price tiers behind one key and one adapter — which is exactly the
    # shape the cost router wants: draft cheap, shortlist mid, finish dear.
    ModelSpec(
        provider_id="veo", model_id="veo-3.1-lite-generate-preview", kind="video",
        display_name="Veo 3.1 Lite",
        capabilities=frozenset({"text_to_video", "image_to_video"}),
        input_types=("text", "image"), output_types=("video",),
        supported_resolutions=("1080x1920",), supported_durations=(2.0, 8.0),
        supports_image_to_video=True, generates_audio=True,
        cost_unit="per_second", cost_per_unit=0.05,
        quality_tier="economy", latency_tier="fast", fidelity_score=0.78,
        fallback_priority=5, requires_key="VEO_API_KEY",
        model_id_setting="VEO_VIDEO_MODEL_ECONOMY",
        docs_url="https://ai.google.dev/gemini-api/docs/models/veo-3.1-lite-generate-preview",
        verified_at="2026-09-12",
        notes_ar="الطبقة الرخيصة — للمسودات والمعاينة قبل الموافقة.",
        notes_en="Cheap tier — drafts and previews before approval.",
    ),
    ModelSpec(
        provider_id="veo", model_id="veo-3.1-fast-generate-preview", kind="video",
        display_name="Veo 3.1 Fast",
        capabilities=frozenset({"text_to_video", "image_to_video"}),
        input_types=("text", "image"), output_types=("video",),
        supported_resolutions=("1080x1920",), supported_durations=(2.0, 8.0),
        supports_image_to_video=True, generates_audio=True,
        cost_unit="per_second", cost_per_unit=0.15,
        quality_tier="standard", latency_tier="fast", fidelity_score=0.88,
        fallback_priority=10, requires_key="VEO_API_KEY",
        model_id_setting="VEO_VIDEO_MODEL",
        docs_url="https://ai.google.dev/gemini-api/docs/veo",
        verified_at="2026-09-12",
        notes_ar="الافتراضي — معظم المشاهد تنتج من هنا.",
        notes_en="The default: most scenes are produced at this tier.",
    ),
    ModelSpec(
        provider_id="veo", model_id="veo-3.1-generate-preview", kind="video",
        display_name="Veo 3.1",
        capabilities=frozenset({"text_to_video", "image_to_video"}),
        input_types=("text", "image"), output_types=("video",),
        supported_resolutions=("1080x1920",), supported_durations=(2.0, 8.0),
        supports_image_to_video=True, supports_first_last_frame=True,
        generates_audio=True,
        cost_unit="per_second", cost_per_unit=0.40,
        quality_tier="flagship", latency_tier="slow", fidelity_score=0.96,
        fallback_priority=30, requires_key="VEO_API_KEY",
        model_id_setting="VEO_VIDEO_MODEL_PREMIUM",
        docs_url="https://ai.google.dev/gemini-api/docs/models/veo-3.1-generate-preview",
        verified_at="2026-09-12",
        notes_ar="للقطة البطل/الخطاف فقط — ثمانية ثوانٍ منه تعادل نصف ميزانية إعلان.",
        notes_en="Hook/hero shot only — eight seconds here is half an ad's budget.",
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
        fallback_priority=20, requires_key="RUNWAY_API_KEY", model_id_setting="RUNWAY_VIDEO_MODEL",
        docs_url="https://docs.dev.runwayml.com/",
        verified_at=None,
        notes_ar="احتياطي إذا Veo رفض المشهد. الاسم غير مؤكد — ثبّته من التوثيق قبل التفعيل.",
        notes_en="Fallback when Veo refuses a scene. Id unverified — confirm before enabling.",
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
        enabled=False,
        fallback_priority=900, requires_key="SEEDANCE_API_KEY",
        model_id_setting="SEEDANCE_VIDEO_MODEL",
        docs_url="",
        verified_at=None,
        notes_ar=(
            "معطّل: ماكو توثيق API رسمي متحقق منه لهذا المزود. "
            "Veo 3.1 Lite يغطي نفس الطبقة السعرية وهو مؤكد."
        ),
        notes_en=(
            "Disabled: no official API reference for this vendor could be verified, so the "
            "endpoint and id here are unusable as-is. Veo 3.1 Lite covers the same price tier "
            "with a documented id."
        ),
    ),
    ModelSpec(
        provider_id="openai", model_id="sora-2-pro", kind="video",
        display_name="OpenAI Sora 2 Pro (retired)",
        capabilities=frozenset({"text_to_video", "image_to_video"}),
        input_types=("text", "image"), output_types=("video",),
        supported_resolutions=("1080x1920",), supported_durations=(2.0, 20.0),
        supports_image_to_video=True, generates_audio=True,
        cost_unit="per_second", cost_per_unit=0.50,
        quality_tier="flagship", latency_tier="slow", fidelity_score=0.94,
        enabled=False, deprecated=True, sunset_date="2026-09-24",
        fallback_priority=999, requires_key="OPENAI_API_KEY",
        docs_url="https://developers.openai.com/api/docs/guides/video-generation",
        verified_at="2026-09-12",
        notes_ar="متقاعد: OpenAI توقف Videos API بتاريخ 2026-09-24. مذكور هنا حتى ما نرجع نضيفه بالغلط.",
        notes_en=(
            "Retired: OpenAI announced the Videos API and sora-2* models shut down on "
            "2026-09-24. Listed so a future session does not re-add it as a new idea."
        ),
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
    # No vendor sells an Iraqi-dialect voice. The product's answer is a cloned
    # voice from a real Iraqi voice actor (with written consent) driven through
    # the highest-expression model — which is why v3 is the primary, not the
    # cheapest tier.
    ModelSpec(
        provider_id="elevenlabs", model_id="eleven_v3", kind="voice",
        display_name="ElevenLabs v3",
        capabilities=frozenset({"tts", "voice_cloning", "emotional_range"}),
        input_types=("text",), output_types=("audio",),
        supported_durations=(0.5, 300.0),
        cost_unit="per_1k_chars", cost_per_unit=0.18,
        quality_tier="flagship", latency_tier="standard", fidelity_score=0.94,
        fallback_priority=10, requires_key="ELEVENLABS_API_KEY",
        model_id_setting="ELEVENLABS_VOICE_MODEL",
        docs_url="https://elevenlabs.io/docs/models",
        verified_at="2026-09-12",
        notes_ar="الأساسي — 70+ لغة تشمل العربية، وأعلى مدى انفعالي. يُستعمل مع صوت عراقي مستنسخ.",
        notes_en="Primary: 70+ languages incl. Arabic, highest emotional range. Pair with a cloned Iraqi voice.",
    ),
    ModelSpec(
        provider_id="elevenlabs", model_id="eleven_multilingual_v2", kind="voice",
        display_name="ElevenLabs Multilingual v2",
        capabilities=frozenset({"tts", "voice_cloning"}),
        input_types=("text",), output_types=("audio",),
        supported_durations=(0.5, 300.0),
        cost_unit="per_1k_chars", cost_per_unit=0.18,
        quality_tier="premium", latency_tier="standard", fidelity_score=0.9,
        fallback_priority=20, requires_key="ELEVENLABS_API_KEY",
        model_id_setting="ELEVENLABS_VOICE_MODEL",
        docs_url="https://elevenlabs.io/docs/models",
        verified_at="2026-09-12",
        notes_ar="احتياطي مستقر — العربية مدرجة (سعودي/إماراتي).",
        notes_en="Stable fallback — Arabic listed as Saudi Arabia / UAE.",
    ),
    ModelSpec(
        provider_id="elevenlabs", model_id="eleven_flash_v2_5", kind="voice",
        display_name="ElevenLabs Flash v2.5",
        capabilities=frozenset({"tts"}),
        input_types=("text",), output_types=("audio",),
        supported_durations=(0.5, 300.0),
        cost_unit="per_1k_chars", cost_per_unit=0.09,
        quality_tier="economy", latency_tier="fast", fidelity_score=0.72,
        enabled=False,
        fallback_priority=900, requires_key="ELEVENLABS_API_KEY",
        model_id_setting="ELEVENLABS_VOICE_MODEL",
        docs_url="https://elevenlabs.io/docs/models",
        verified_at="2026-09-12",
        notes_ar="معطّل للعربية: العربية غير مدرجة بلغاته المدعومة رغم إنه الأرخص والأسرع.",
        notes_en=(
            "Disabled for this product: cheapest and fastest, but Arabic is NOT in its "
            "documented language list. Enable only for a non-Arabic deployment."
        ),
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
        enabled=False,
        fallback_priority=900, requires_key="MUSIC_API_KEY", model_id_setting="MUSIC_MODEL",
        docs_url="",
        verified_at=None,
        notes_ar=(
            "معطّل: ماكو مزود موسيقى مختار بعد. للإعلانات المدفوعة، مكتبة موسيقى مرخّصة "
            "تجارياً أأمن من التوليد — حقوق البث الإعلاني تكون واضحة."
        ),
        notes_en=(
            "Disabled: no music vendor has been chosen, so this cannot work as configured. "
            "For paid advertising a commercially licensed music library is the safer option "
            "than generation — the broadcast rights are unambiguous. To use a generator, "
            "confirm its API, set MUSIC_BASE_URL / MUSIC_MODEL / MUSIC_API_KEY and rewrite "
            "GenericMusicAdapter's request shape first."
        ),
    ),
]

_BY_KEY: Dict[Tuple[str, str], ModelSpec] = {s.key: s for s in _SPECS}

_QUALITY_RANK = {tier: i for i, tier in enumerate(QUALITY_TIERS)}


def all_specs() -> List[ModelSpec]:
    return list(_SPECS)


def candidates_any_kind() -> List[ModelSpec]:
    """Every model the router could actually pick, across all kinds."""
    out: List[ModelSpec] = []
    for kind in KINDS:
        out.extend(candidates(kind))
    return out


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
    # A vendor-retired model is never selectable, even with include_disabled —
    # that flag exists so the Settings UI can *show* everything, not so the
    # router can route to something that will be switched off.
    out = [s for s in out if not s.deprecated]
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
        enabled = any(s.selectable for s in provider_specs)
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
