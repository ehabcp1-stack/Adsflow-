"""Concept Generation Engine — internally more candidates, three surfaced."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.models import Concept, Project, ProjectAnalysis
from app.providers.registry import get_llm
from app.services.analysis import _brief_dict

REFINE_ACTIONS = [
    {"key": "change_hook", "label_en": "Change Hook", "label_ar": "غيّر الخطّاف"},
    {"key": "more_iraqi", "label_en": "More Iraqi", "label_ar": "أكثر عراقية"},
    {"key": "more_luxury", "label_en": "More Luxury", "label_ar": "أكثر فخامة"},
    {"key": "more_emotional", "label_en": "More Emotional", "label_ar": "أكثر عاطفية"},
    {"key": "more_sales", "label_en": "More Sales-Oriented", "label_ar": "أكثر توجهاً للبيع"},
]


def latest_analysis(db: Session, project: Project) -> Optional[ProjectAnalysis]:
    return (
        db.query(ProjectAnalysis)
        .filter(ProjectAnalysis.project_id == project.id)
        .order_by(ProjectAnalysis.version.desc())
        .first()
    )


def generate_concepts(db: Session, project: Project, *, regenerate: bool = False) -> List[Concept]:
    existing = db.query(Concept).filter(Concept.project_id == project.id).all()
    if existing and not regenerate:
        return sorted(existing, key=lambda c: (c.is_alternative, -c.score_total))

    version = (max((c.version for c in existing), default=0) + 1) if existing else 1
    for concept in existing:
        db.delete(concept)
    db.flush()

    analysis = latest_analysis(db, project)
    llm = get_llm()
    payload = llm.complete_json(
        task="concepts",
        context={
            "brief": _brief_dict(project),
            "recommended_mode": analysis.recommended_mode if analysis else project.production_mode,
            "analysis": analysis.creative_strategy if analysis else {},
        },
    ).data

    created: List[Concept] = []
    for item in payload.get("concepts", []):
        concept = Concept(
            project_id=project.id,
            version=version,
            name=item["name"],
            name_en=item.get("name_en", ""),
            angle=item["angle"],
            one_line_idea=item.get("one_line_idea", ""),
            hook=item.get("hook", ""),
            creative_direction=item.get("creative_direction", ""),
            recommended_mode=item.get("recommended_mode", "hybrid_reel"),
            recommended_voice=item.get("recommended_voice", "iraqi_professional"),
            visual_style=item.get("visual_style", ""),
            cta_style=item.get("cta_style", ""),
            estimated_cost_usd=round(
                (analysis.estimated_cost_usd if analysis else 4.0)
                * (1.25 if item["angle"] in ("luxury", "lifestyle") else 1.0),
                2,
            ),
            why_this_works=item.get("why_this_works", ""),
            scores=item.get("scores", {}),
            score_total=item.get("score_total", 0.0),
            is_recommended=item.get("is_recommended", False),
            is_alternative=item.get("is_alternative", False),
        )
        db.add(concept)
        created.append(concept)
    db.flush()
    return sorted(created, key=lambda c: (c.is_alternative, -c.score_total))


def select_concept(db: Session, project: Project, concept_id: str) -> Concept:
    concept = db.get(Concept, concept_id)
    if not concept or concept.project_id != project.id:
        raise NotFound("Concept not found.", "الفكرة غير موجودة.")
    for other in project.concepts:
        other.is_selected = other.id == concept.id
    project.selected_concept_id = concept.id
    db.flush()
    return concept


def refine_concept(db: Session, project: Project, concept: Concept, action: str) -> Concept:
    llm = get_llm()
    hook = llm.complete_json(task="refine", context={"action": action, "text": concept.hook}).data["text"]
    concept.hook = hook
    if action in ("more_luxury", "more_emotional", "more_sales", "more_iraqi"):
        concept.creative_direction = llm.complete_json(
            task="refine", context={"action": action, "text": concept.creative_direction}
        ).data["text"]
    concept.version += 1
    db.flush()
    return concept


def concept_payload(concept: Concept) -> Dict[str, Any]:
    return {
        "id": concept.id,
        "name": concept.name,
        "name_en": concept.name_en,
        "angle": concept.angle,
        "one_line_idea": concept.one_line_idea,
        "hook": concept.hook,
        "creative_direction": concept.creative_direction,
        "recommended_mode": concept.recommended_mode,
        "recommended_voice": concept.recommended_voice,
        "visual_style": concept.visual_style,
        "cta_style": concept.cta_style,
        "estimated_cost_usd": concept.estimated_cost_usd,
        "why_this_works": concept.why_this_works,
        "scores": concept.scores,
        "score_total": concept.score_total,
        "is_recommended": concept.is_recommended,
        "is_selected": concept.is_selected,
        "is_alternative": concept.is_alternative,
        "version": concept.version,
    }
