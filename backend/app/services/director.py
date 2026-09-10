"""AI Director — short, useful recommendations shown across the workflow."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.enums import ProductionMethod, WorkflowStage
from app.models import Project, Scene, Storyboard


def director_note(*, key: str, en: str, ar: str, impact: str = "medium", action: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"key": key, "message_en": en, "message_ar": ar, "impact": impact, "action": action}


def notes_for_storyboard(db: Session, project: Project, storyboard: Storyboard) -> List[Dict[str, Any]]:
    scenes: List[Scene] = list(storyboard.scenes)
    notes: List[Dict[str, Any]] = []
    ai_video_scenes = [s for s in scenes if s.production_method == ProductionMethod.AI_VIDEO.value]
    if len(ai_video_scenes) > 1:
        savings = round(sum(s.estimated_cost_usd for s in ai_video_scenes[1:]) * 0.85, 2)
        notes.append(
            director_note(
                key="single_hero",
                en=f"I recommend generating only one cinematic hero shot — saves about ${savings:.2f}.",
                ar=f"أنصح بتوليد لقطة سينمائية وحدة بس — توفر تقريباً ${savings:.2f}.",
                impact="high",
                action={"type": "downgrade_extra_ai_video", "scene_ids": [s.id for s in ai_video_scenes[1:]]},
            )
        )
    for scene in scenes:
        if scene.production_method == ProductionMethod.AI_VIDEO.value and not scene.is_hook and not scene.is_hero:
            saving = round(scene.estimated_cost_usd - 0.02, 2)
            notes.append(
                director_note(
                    key=f"cheaper_scene_{scene.scene_number}",
                    en=f"Replacing Scene {scene.scene_number} with Photo Motion saves approximately ${saving:.2f}.",
                    ar=f"استبدال المشهد {scene.scene_number} بحركة صورة يوفر تقريباً ${saving:.2f}.",
                    impact="medium",
                    action={"type": "make_cheaper", "scene_id": scene.id},
                )
            )
    if not any(s.is_hook for s in scenes):
        notes.append(
            director_note(
                key="missing_hook",
                en="No scene is marked as the hook — the first 3 seconds decide watch-through.",
                ar="ما أكو مشهد محدد كخطّاف — أول ٣ ثواني هي اللي تقرر نسبة المشاهدة.",
                impact="high",
            )
        )
    return notes[:4]


def notes_for_stage(db: Session, project: Project, stage: WorkflowStage) -> List[Dict[str, Any]]:
    if stage == WorkflowStage.CONCEPTS:
        best = max(project.concepts, key=lambda c: c.score_total, default=None)
        if best:
            return [
                director_note(
                    key="best_concept",
                    en=f"“{best.name_en or best.name}” has the highest expected conversion fit ({best.score_total:.0f}/100).",
                    ar=f"«{best.name}» عنده أعلى ملاءمة متوقعة للتحويل ({best.score_total:.0f}/١٠٠).",
                    impact="high",
                )
            ]
    if stage == WorkflowStage.VOICE:
        return [
            director_note(
                key="voice_lock",
                en="Lock the voice before the storyboard — scene timing is derived from it.",
                ar="ثبّت الصوت قبل الستوري بورد — توقيت المشاهد ينبني على مدة التعليق.",
                impact="medium",
            )
        ]
    if stage == WorkflowStage.EDIT:
        return [
            director_note(
                key="captions",
                en="Arabic captions are rendered by our editor, never by the video model — keep them on for silent viewing.",
                ar="الكابشن العربي ينرسم من محررنا مو من موديل الفيديو — خليه شغال لأن أغلب المشاهدات بدون صوت.",
                impact="medium",
            )
        ]
    return []
