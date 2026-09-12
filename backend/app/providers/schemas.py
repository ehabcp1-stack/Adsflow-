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

from pydantic import BaseModel, Field, ValidationError


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


class QCResult(BaseModel):
    """Output of the `qc` task."""

    scores: Dict[str, float]
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
