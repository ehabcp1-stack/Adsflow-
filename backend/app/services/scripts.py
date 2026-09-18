"""Script Engine: Hook Builder · Iraqi Dialect Writer · VO Writer ·
On-Screen Copy Writer · Timing Engine · CTA Engine · Script Critic."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.services import script_qa
from app.core.db import fit
from app.models import BrandKit, Concept, Project, ScriptVersion
from app.providers.registry import get_llm
from app.services.analysis import _brief_dict
from app.services.dialect import estimate_speech_seconds, to_on_screen

VARIANTS = ["primary", "more_sales", "more_emotional"]

REFINE_ACTIONS = [
    {"key": "more_iraqi", "label_en": "More Iraqi", "label_ar": "أكثر عراقية"},
    {"key": "more_premium", "label_en": "More Premium", "label_ar": "أكثر فخامة"},
    {"key": "more_direct", "label_en": "More Direct", "label_ar": "أكثر مباشرة"},
    {"key": "shorter", "label_en": "Shorter", "label_ar": "أقصر"},
    {"key": "stronger_hook", "label_en": "Stronger Hook", "label_ar": "خطّاف أقوى"},
    {"key": "change_cta", "label_en": "Change CTA", "label_ar": "غيّر الدعوة"},
]


def _brand(db: Session, project: Project) -> Optional[BrandKit]:
    return db.get(BrandKit, project.brand_kit_id) if project.brand_kit_id else None


def generate_scripts(db: Session, project: Project, *, regenerate: bool = False) -> List[ScriptVersion]:
    """Generate the primary script plus its two variations."""
    if not project.selected_concept_id:
        raise NotFound("Select a concept before writing the script.", "اختر الفكرة قبل كتابة النص.")
    concept = db.get(Concept, project.selected_concept_id)
    existing = db.query(ScriptVersion).filter(ScriptVersion.project_id == project.id).all()
    if existing and not regenerate:
        return sorted(existing, key=lambda s: (VARIANTS.index(s.variant) if s.variant in VARIANTS else 9, -s.version))

    version = (max((s.version for s in existing), default=0) + 1) if existing else 1
    brand = _brand(db, project)
    llm = get_llm()
    created: List[ScriptVersion] = []

    for variant in VARIANTS:
        data = llm.complete_json(
            task="script",
            context={
                "brief": _brief_dict(project),
                "concept": {
                    "hook": concept.hook if concept else "",
                    "recommended_voice": concept.recommended_voice if concept else project.dialect,
                    "angle": concept.angle if concept else "emotional",
                },
                "variant": variant,
                "brand": {
                    # The writer needs the real contact details: a CTA that says
                    # "call us" without a number is a defect QC will catch.
                    "name": (brand.name_ar or brand.name) if brand else "",
                    "phone": brand.phone if brand else None,
                    "website": brand.website if brand else None,
                    "preferred_phrases": (brand.preferred_phrases if brand else []) or [],
                    "pronunciation_rules": (brand.pronunciation_rules if brand else {}) or {},
                },
                "forbidden_phrases": (brand.forbidden_phrases if brand else []) or [],
            },
        ).data

        # Second pass: read the script back the way an Iraqi copywriter would,
        # repair what can be repaired deterministically, and record the score
        # of what the user is actually shown — not of the first draft.
        brand_context = {
            "phone": brand.phone if brand else None,
            "forbidden_phrases": (brand.forbidden_phrases if brand else []) or [],
            "preferred_phrases": (brand.preferred_phrases if brand else []) or [],
        }
        data, qa_report, qa_changes = script_qa.qa_pass(
            data,
            preset=data.get("dialect_preset") or project.dialect,
            brand=brand_context,
            target_duration_sec=float(project.duration_sec),
        )
        critic_notes = list(data.get("critic_notes") or []) + qa_report.notes_ar()
        if qa_changes:
            critic_notes.append(f"تم تعديل النص تلقائياً ({len(qa_changes)} تصحيح لغوي)")

        script = ScriptVersion(
            project_id=project.id,
            concept_id=project.selected_concept_id,
            version=version,
            variant=variant,
            hook=data["hook"],
            body=data["body"],
            cta=data["cta"],
            voice_over_text=data["voice_over_text"],
            on_screen_text=data["on_screen_text"],
            lines=data["lines"],
            dialect_preset=fit(ScriptVersion, "dialect_preset", data.get("dialect_preset"), "iraqi_professional"),
            total_duration_sec=data["total_duration_sec"],
            word_count=data["word_count"],
            score=qa_report.score,
            critic_notes=critic_notes,
            is_selected=variant == "primary",
        )
        db.add(script)
        created.append(script)

    db.flush()
    primary = next((s for s in created if s.variant == "primary"), created[0])
    project.selected_script_id = primary.id
    db.flush()
    return created


def select_script(db: Session, project: Project, script_id: str) -> ScriptVersion:
    script = db.get(ScriptVersion, script_id)
    if not script or script.project_id != project.id:
        raise NotFound("Script not found.", "النص غير موجود.")
    for other in project.scripts:
        other.is_selected = other.id == script.id
    project.selected_script_id = script.id
    db.flush()
    return script


def _retime(lines: List[Dict[str, Any]], duration: float) -> List[Dict[str, Any]]:
    raw = [max(estimate_speech_seconds(line["voice_line"]), 1.2) for line in lines] or [1.0]
    scale = duration / sum(raw)
    cursor = 0.0
    for line, seconds in zip(lines, raw):
        length = round(seconds * scale, 2)
        line["start"] = round(cursor, 2)
        cursor = min(cursor + length, duration)
        line["end"] = round(cursor, 2)
        line["on_screen_text"] = to_on_screen(line["voice_line"])
    if lines:
        lines[-1]["end"] = duration
    return lines


def refine_script(
    db: Session, project: Project, script: ScriptVersion, action: str, *, new_cta: Optional[str] = None
) -> ScriptVersion:
    """Refinements never lose the selected concept — a new version is created."""
    llm = get_llm()
    lines = [dict(line) for line in (script.lines or [])]

    for line in lines:
        if action == "stronger_hook" and line.get("role") != "hook":
            continue
        if action == "change_cta" and line.get("role") != "cta":
            continue
        if action == "change_cta":
            line["voice_line"] = new_cta or line["voice_line"]
            continue
        line["voice_line"] = llm.complete_json(
            task="refine", context={"action": action, "text": line["voice_line"]}
        ).data["text"]

    lines = _retime(lines, script.total_duration_sec)
    voice_over = " ".join(line["voice_line"] for line in lines)

    new_version = ScriptVersion(
        project_id=project.id,
        concept_id=script.concept_id,  # concept is preserved
        version=script.version + 1,
        variant=script.variant,
        hook=next((line["voice_line"] for line in lines if line.get("role") == "hook"), script.hook),
        body=" ".join(line["voice_line"] for line in lines if line.get("role") == "body"),
        cta=next((line["voice_line"] for line in lines if line.get("role") == "cta"), script.cta),
        voice_over_text=voice_over,
        on_screen_text=[
            {"index": line["index"], "text": line["on_screen_text"], "start": line["start"], "end": line["end"]}
            for line in lines
        ],
        lines=lines,
        dialect_preset=script.dialect_preset,
        total_duration_sec=script.total_duration_sec,
        word_count=len(voice_over.split()),
        score=min(99.0, script.score + 1.5),
        critic_notes=script.critic_notes,
        is_selected=script.is_selected,
    )
    db.add(new_version)
    db.flush()
    if script.is_selected:
        select_script(db, project, new_version.id)
    return new_version


def update_script_text(db: Session, project: Project, script: ScriptVersion, lines: List[Dict[str, Any]]) -> ScriptVersion:
    """Manual edit from the Script screen → new version, concept preserved."""
    normalized = _retime([dict(line) for line in lines], script.total_duration_sec)
    voice_over = " ".join(line["voice_line"] for line in normalized)
    new_version = ScriptVersion(
        project_id=project.id,
        concept_id=script.concept_id,
        version=script.version + 1,
        variant=script.variant,
        hook=next((line["voice_line"] for line in normalized if line.get("role") == "hook"), ""),
        body=" ".join(line["voice_line"] for line in normalized if line.get("role") == "body"),
        cta=next((line["voice_line"] for line in normalized if line.get("role") == "cta"), ""),
        voice_over_text=voice_over,
        on_screen_text=[
            {"index": line["index"], "text": line["on_screen_text"], "start": line["start"], "end": line["end"]}
            for line in normalized
        ],
        lines=normalized,
        dialect_preset=script.dialect_preset,
        total_duration_sec=script.total_duration_sec,
        word_count=len(voice_over.split()),
        score=script.score,
        critic_notes=script.critic_notes,
        hook_variant=script.hook_variant,
        is_selected=script.is_selected,
    )
    db.add(new_version)
    db.flush()
    if script.is_selected:
        select_script(db, project, new_version.id)
    return new_version


def script_payload(script: ScriptVersion) -> Dict[str, Any]:
    return {
        "id": script.id,
        "version": script.version,
        "variant": script.variant,
        "hook": script.hook,
        "body": script.body,
        "cta": script.cta,
        "voice_over_text": script.voice_over_text,
        "on_screen_text": script.on_screen_text,
        "lines": script.lines,
        "dialect_preset": script.dialect_preset,
        "total_duration_sec": script.total_duration_sec,
        "word_count": script.word_count,
        "score": script.score,
        "critic_notes": script.critic_notes,
        "hook_variant": script.hook_variant,
        "is_selected": script.is_selected,
        "concept_id": script.concept_id,
        # Every word the dialect layer thinks is not Iraqi, with what to put
        # instead — per line, so the screen can offer the swap where the word
        # actually is. The user asked for this directly: he wants to fix any
        # word he sees as wrong himself, because he is the one who knows how
        # people talk where the ad runs.
        "dialect_flags": dialect_flags(script),
    }


def dialect_flags(script: ScriptVersion) -> List[Dict[str, Any]]:
    """Non-Iraqi words in this script, located by line and by character.

    Only the spoken lines are searched. `hook`, `cta` and `voice_over_text`
    are derived from those same lines every time the script is saved
    (`update_script_text`), so flagging them too would show the user the same
    word twice and offer him a swap in a place that gets overwritten.

    `line_index` is the position in `lines`, which is the array the screen
    edits; `start`/`end` locate the word inside that line's `voice_line`.
    """
    from app.services.dialect import find_non_iraqi

    preset_name = script.dialect_preset or "iraqi_professional"
    out: List[Dict[str, Any]] = []
    for index, line in enumerate(script.lines or []):
        spoken = (line or {}).get("voice_line") or ""
        for flag in find_non_iraqi(spoken, preset_name=preset_name):
            out.append({"line_index": index, **flag.as_dict()})
    return out
