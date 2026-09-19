"""Structured-output contracts for engine-to-engine communication.

Every real LLM adapter asks the vendor for JSON and must validate it before
any downstream service sees it — a malformed or partial response must never
propagate past `complete_json()`. These Pydantic v2 models are that contract:
one model per `MockLLMProvider` task (see `app/providers/mock.py`'s
`_task_*` methods, which these mirror field-for-field) plus a few models used
for structured hand-offs that are not tied to a single LLM call (voice
direction, model routing, auto-fix instructions).

`validate_llm_json()` never raises — a bad payload comes back as
`(False, None, [errors])` so the adapter can attempt exactly one repair pass
via `repair_prompt()` and then give up cleanly.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Type

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.core.enums import ProductionMethod


# --------------------------------------------------------------------------
# Shared building blocks
# --------------------------------------------------------------------------
class AnalysisResult(BaseModel):
    """Output of the `brief_interpretation` task."""

    objective: str
    objective_ar: str
    audience_summary: str
    platform_notes: str
    language_plan: Dict[str, str] = Field(default_factory=dict)
    key_messages: List[str] = Field(default_factory=list)
    must_include: List[str] = Field(default_factory=list)
    risk_notes: List[str] = Field(default_factory=list)


class ProductionRecommendation(BaseModel):
    """Output of the `creative_strategy` task — mode/angle recommendation."""

    recommended_angle: str
    alternative_angles: List[str] = Field(default_factory=list)
    recommended_mode: str
    recommended_voice_style: str
    marketing_angle_ar: str
    pacing: str


class ConceptCandidate(BaseModel):
    angle: str
    name: str
    name_en: str
    one_line_idea: str
    hook: str
    creative_direction: str
    recommended_mode: str
    recommended_voice: str
    visual_style: str
    cta_style: str
    why_this_works: str
    scores: Dict[str, float] = Field(default_factory=dict)
    score_total: float
    is_alternative: bool = False
    is_recommended: bool = False


class ConceptsResult(BaseModel):
    """Output of the `concepts` task."""

    concepts: List[ConceptCandidate]


class ScriptLine(BaseModel):
    index: int
    role: str
    voice_line: str
    on_screen_text: str
    start: float
    end: float

    @field_validator("role")
    @classmethod
    def _role_must_be_one_of_three(cls, value: str) -> str:
        """A reel is an opening, a middle and an ask. Nothing else is a role.

        This was a free string, and six branches across three services compare
        it exactly. A live script came back with every line marked `narrator`,
        so `hook`, `body` and `cta` were all derived as empty — and the voice
        preview, which speaks `script.hook`, was handed an empty string and
        produced silence. The user heard a preview that "cuts off straight
        away"; it had never started.
        """
        text = (value or "").strip().lower()
        if text not in ("hook", "body", "cta"):
            raise ValueError(f"role must be one of ('hook', 'body', 'cta'); got {value!r}")
        return text


class OnScreenTextEntry(BaseModel):
    index: int
    text: str
    start: float
    end: float


class ScriptVersionOut(BaseModel):
    """Output of the `script` task."""

    hook: str
    body: str
    cta: str
    voice_over_text: str
    on_screen_text: List[OnScreenTextEntry] = Field(default_factory=list)
    lines: List[ScriptLine] = Field(default_factory=list)
    dialect_preset: str
    total_duration_sec: float
    word_count: int
    score: float
    critic_notes: List[str] = Field(default_factory=list)


class VoiceDirection(BaseModel):
    """Structured direction handed to a voice adapter for one line/scene.

    Not produced by a `MockLLMProvider` task directly — the AI Director
    composes this from the approved script before calling `VoiceProvider.synthesize()`.
    """

    voice_id: str
    dialect_preset: str
    speed: float = 1.0
    energy: float = 0.6
    emotion: float = 0.5
    notes_ar: str = ""


class ScenePlan(BaseModel):
    scene_number: int
    start_time: float
    end_time: float
    purpose: str
    voice_line: str
    visual_source: str
    selected_asset_id: Optional[str] = None
    visual_direction: str
    camera_direction: str
    camera_movement: str
    lighting: str
    on_screen_text: str
    text_animation: str
    music_instruction: str
    sfx_instruction: str
    transition: str
    production_method: str
    is_hook: bool = False
    is_hero: bool = False
    priority: int = 50

    @field_validator("production_method")
    @classmethod
    def _method_must_exist(cls, value: str) -> str:
        """A production method the code does not implement is not a plan.

        This field used to be a free string, and it decided which branch
        `production.__produce_scene` takes. A live storyboard came back with
        `kenburns_zoom_on_photo` and `text_card_cta_overlay` — descriptive,
        plausible, and in no enum anywhere. Neither matched `LOCAL_METHODS`,
        so four scenes that should have been rendered from the customer's own
        photo with FFmpeg at no cost went to the image provider instead,
        which on that server is the mock. It wrote four SVG frames, marked
        them `passed` at quality 95, assembly found no clips to join, and the
        customer got a placeholder reel that QC then scored 61 out of 100.

        Nothing along that path was broken. Every step did exactly what it
        was told with a value no step recognised. So the value is checked
        here, at the boundary, where a wrong answer is still just a failed
        validation and costs one repair attempt.
        """
        allowed = {method.value for method in ProductionMethod}
        text = (value or "").strip().lower()
        if text not in allowed:
            raise ValueError(
                f"production_method must be one of {sorted(allowed)}; got {value!r}"
            )
        return text


class StoryboardOut(BaseModel):
    """Output of the `storyboard` task."""

    scenes: List[ScenePlan]


class ModelRoute(BaseModel):
    """Structured mirror of `model_router.RoutingDecision`.

    Used when a routing choice needs to travel through a structured-output
    contract (e.g. an LLM-assisted override, or Director Mode audit trail)
    rather than staying an in-process dataclass.
    """

    method: str
    provider: str
    model: str
    estimated_cost_usd: float
    reason_en: str
    reason_ar: str
    downgraded: bool = False


class QCIssue(BaseModel):
    code: str
    severity: str
    message_ar: str


class QCRecommendation(BaseModel):
    code: str
    message_ar: str
    impact: str


#: The six dimensions `services/qc.WEIGHTS` actually weighs. Anything else a
#: model volunteers is not a QC dimension, whatever it is called.
QC_DIMENSIONS = (
    "visual_quality",
    "audio_voice",
    "arabic_quality",
    "marketing_effectiveness",
    "brand_consistency",
    "platform_fit",
)


class QCScores(BaseModel):
    """The six weighted dimensions, each 0-100.

    This was `Dict[str, float]`: any keys, any values. A live report came back
    with the model's own vocabulary on its own scale —
    `dialect_authenticity: 0.92`, `cta_clarity: 0.55`, `overall: 0.68` — none
    of which is weighted, so five of the six real dimensions silently fell
    back to their 85/90 defaults. The exception was `brand_consistency: 0`,
    which *is* weighted: the model meant nought percent, the code read nought
    out of a hundred, and ten points of the final score vanished into a units
    mismatch. The screen then listed the invented names as rows scored 1 and
    0, because 0.92 rounds to 1.

    Extra keys are dropped rather than rejected — a model that adds a note of
    its own should not fail the whole report — but they never reach the score
    or the screen.
    """

    model_config = ConfigDict(extra="ignore")

    visual_quality: float = Field(ge=0, le=100)
    audio_voice: float = Field(ge=0, le=100)
    arabic_quality: float = Field(ge=0, le=100)
    marketing_effectiveness: float = Field(ge=0, le=100)
    brand_consistency: float = Field(ge=0, le=100)
    platform_fit: float = Field(ge=0, le=100)

    @model_validator(mode="before")
    @classmethod
    def _to_percent(cls, data: Any) -> Any:
        """Accept a 0-1 answer and say so in the only unit we score in.

        Asking for 0-100 does not stop a model answering 0.92, and 0.92 is
        indistinguishable from a catastrophic 0.92/100 unless the whole set is
        read together. Every value at or below 1 is the 0-1 scale — a real
        report in which all six dimensions score one point out of a hundred
        does not exist, and if it did, a placeholder check would already have
        failed it. Anything mixed is left alone: that is a model disagreeing
        with itself, and a failed validation says so better than a guess.
        """
        if not isinstance(data, dict):
            return data
        values = [v for k, v in data.items() if k in QC_DIMENSIONS and isinstance(v, (int, float))]
        if values and all(0 <= float(v) <= 1 for v in values):
            return {
                key: (round(float(value) * 100, 1) if key in QC_DIMENSIONS and isinstance(value, (int, float)) else value)
                for key, value in data.items()
            }
        return data


class QCResult(BaseModel):
    """Output of the `qc` task."""

    scores: QCScores
    issues: List[QCIssue] = Field(default_factory=list)
    recommendations: List[QCRecommendation] = Field(default_factory=list)


class AutoFixInstruction(BaseModel):
    """One targeted repair — CLAUDE.md §12: auto-fix touches only the
    affected component, never a full regeneration."""

    target_component: str  # e.g. "caption" | "voice_line" | "scene" | "audio_mix"
    target_id: Optional[str] = None
    action: str
    reason_ar: str
    reason_en: str = ""


class RefineResult(BaseModel):
    """Output of the `refine` task."""

    text: str
    action: str


#: task name (MockLLMProvider._task_<name>) -> the schema it must produce.
TASK_MODELS: Dict[str, Type[BaseModel]] = {
    "brief_interpretation": AnalysisResult,
    "creative_strategy": ProductionRecommendation,
    "concepts": ConceptsResult,
    "script": ScriptVersionOut,
    "storyboard": StoryboardOut,
    "qc": QCResult,
    "refine": RefineResult,
}


def json_schema_for(task: str) -> Dict[str, Any]:
    """JSON Schema for `task`, or `{}` for a task with no structured contract.

    Sent to real LLM adapters as part of the request (e.g. OpenAI's
    `response_format` / Gemini's `response_schema`) so the vendor is asked
    to shape its own output, on top of the validation below.
    """
    model = TASK_MODELS.get(task)
    return model.model_json_schema() if model else {}


def validate_llm_json(task: str, payload: Dict[str, Any]) -> Tuple[bool, Optional[BaseModel], List[str]]:
    """Validate `payload` against `task`'s schema. Never raises.

    An unknown task has no schema to check against — treated as valid so a
    future task name doesn't hard-fail every adapter that doesn't know it
    yet (the mock provider already handles unknown tasks the same way).
    """
    model = TASK_MODELS.get(task)
    if model is None:
        return True, None, []
    if not isinstance(payload, dict):
        return False, None, [f"expected a JSON object for task '{task}', got {type(payload).__name__}"]
    try:
        instance = model.model_validate(payload)
        return True, instance, []
    except ValidationError as exc:
        errors = [f"{'.'.join(str(part) for part in err['loc']) or '<root>'}: {err['msg']}" for err in exc.errors()]
        return False, None, errors


def repair_prompt(task: str, errors: List[str]) -> str:
    """Short instruction for the ONE allowed structured-output retry.

    Callers must not loop this — adapters enforce a single repair attempt
    (see `adapters.py`'s `_complete_json_with_repair`).
    """
    schema = json_schema_for(task)
    required = ", ".join(schema.get("required", [])) or "the required fields"
    joined = "; ".join(errors[:8]) or "the response did not match the expected schema"
    return (
        f"Your previous JSON response for task '{task}' was invalid: {joined}. "
        f"Reply again with ONLY a single valid JSON object containing {required}. "
        "No prose, no markdown code fences, no explanation — JSON only."
    )
