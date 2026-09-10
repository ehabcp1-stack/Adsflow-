"""Final QC Engine + Auto Fix.

Weighted score: Visual 25 · Audio 20 · Arabic 15 · Marketing 20 · Brand 10 · Platform 10
Thresholds: 90+ approved · 85–89 review recommended · <85 fix required.
Critical errors override the score.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import ProjectState
from app.core.errors import NotFound
from app.models import BrandKit, Project, QCReport, Render, ScriptVersion, Storyboard
from app.providers.registry import get_llm
from app.services import approvals as approval_service
from app.services.editing import active_render
from app.services.storyboards import active_storyboard

WEIGHTS = {
    "visual_quality": 25,
    "audio_voice": 20,
    "arabic_quality": 15,
    "marketing_effectiveness": 20,
    "brand_consistency": 10,
    "platform_fit": 10,
}

QC_LEVELS = [
    {"key": "visual", "label_en": "Visual QC", "label_ar": "فحص بصري"},
    {"key": "arabic", "label_en": "Arabic & Caption QC", "label_ar": "فحص العربي والكابشن"},
    {"key": "audio", "label_en": "Voice & Audio QC", "label_ar": "فحص الصوت"},
    {"key": "marketing", "label_en": "Marketing QC", "label_ar": "فحص تسويقي"},
    {"key": "brand", "label_en": "Brand QC", "label_ar": "فحص الهوية"},
]

CRITICAL_CODES = {
    "wrong_phone_number",
    "wrong_project_name",
    "arabic_error",
    "product_distortion",
    "missing_cta",
}


def _critical_checks(
    project: Project, script: Optional[ScriptVersion], brand: Optional[BrandKit], storyboard: Optional[Storyboard]
) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    vo = (script.voice_over_text if script else "") or ""
    on_screen = " ".join(item.get("text", "") for item in (script.on_screen_text if script else []) or [])

    if not (project.cta and (project.cta in vo or project.cta in on_screen or (script and script.cta))):
        issues.append(
            {"code": "missing_cta", "severity": "critical", "message_en": "No call to action in the final cut.",
             "message_ar": "ما أكو دعوة للتواصل بالنسخة النهائية."}
        )
    if brand and brand.phone and brand.phone not in (on_screen + vo + (project.key_information or "")):
        issues.append(
            {"code": "wrong_phone_number", "severity": "warning",
             "message_en": "Brand phone number never appears — confirm the contact shown on screen.",
             "message_ar": "رقم الهاتف ما يظهر — تأكد من رقم التواصل المعروض."}
        )
    if project.name and project.name not in (vo + on_screen):
        issues.append(
            {"code": "wrong_project_name", "severity": "warning",
             "message_en": "Project name is never spoken or shown.",
             "message_ar": "اسم المشروع ما ينذكر ولا يظهر."}
        )
    if storyboard:
        low = [s for s in storyboard.scenes if (s.quality_score or 100) < 80]
        if low:
            issues.append(
                {"code": "product_distortion", "severity": "critical" if any((s.quality_score or 100) < 70 for s in low) else "warning",
                 "message_en": f"{len(low)} scene(s) below the quality bar.",
                 "message_ar": f"أكو {len(low)} مشهد تحت حد الجودة.",
                 "scene_ids": [s.id for s in low]}
            )
    return issues


def run_qc(db: Session, project: Project, *, render: Optional[Render] = None) -> QCReport:
    render = render or active_render(db, project)
    if not render:
        raise NotFound("Render the project before running QC.", "لازم تسوي مونتاج قبل الفحص.")
    storyboard = active_storyboard(db, project)
    script = db.get(ScriptVersion, project.selected_script_id) if project.selected_script_id else None
    brand = db.get(BrandKit, project.brand_kit_id) if project.brand_kit_id else None

    llm_out = get_llm().complete_json(
        task="qc",
        context={
            "project": {"id": project.id, "name": project.name, "cta": project.cta},
            "script": {"voice_over_text": script.voice_over_text if script else "", "cta": script.cta if script else ""},
            "brand": {"phone": brand.phone if brand else None},
            "render_version": render.version,
        },
    ).data

    scores: Dict[str, float] = llm_out.get("scores", {})
    if storyboard and storyboard.scenes:
        avg_scene = sum((s.quality_score or 90) for s in storyboard.scenes) / len(storyboard.scenes)
        scores["visual_quality"] = round((scores.get("visual_quality", 90) + avg_scene) / 2, 1)
    if not project.voice_over_enabled:
        scores["audio_voice"] = round(min(scores.get("audio_voice", 90), 82), 1)

    total = round(sum(scores.get(key, 85) * weight for key, weight in WEIGHTS.items()) / sum(WEIGHTS.values()), 1)

    issues = _critical_checks(project, script, brand, storyboard) + [
        dict(item, severity=item.get("severity", "warning")) for item in llm_out.get("issues", [])
    ]
    criticals = [i for i in issues if i.get("severity") == "critical" and i.get("code") in CRITICAL_CODES]

    if criticals:
        verdict = "fix_required"
    elif total >= settings.QC_APPROVE_THRESHOLD:
        verdict = "approved"
    elif total >= settings.QC_REVIEW_THRESHOLD:
        verdict = "review"
    else:
        verdict = "fix_required"

    checks = [
        {
            "level": level["key"],
            "label_en": level["label_en"],
            "label_ar": level["label_ar"],
            "passed": not any(i.get("severity") == "critical" for i in issues),
            "score": scores.get(
                {"visual": "visual_quality", "arabic": "arabic_quality", "audio": "audio_voice",
                 "marketing": "marketing_effectiveness", "brand": "brand_consistency"}[level["key"]],
                90,
            ),
        }
        for level in QC_LEVELS
    ]

    last = db.query(QCReport).filter(QCReport.project_id == project.id).order_by(QCReport.version.desc()).first()
    report = QCReport(
        project_id=project.id,
        render_id=render.id,
        version=(last.version + 1) if last else 1,
        scores=scores,
        total_score=total,
        verdict=verdict,
        critical_issues=criticals,
        recommendations=llm_out.get("recommendations", []) + [
            {"code": i["code"], "message_ar": i["message_ar"], "impact": "high"} for i in issues if i not in criticals
        ],
        checks=checks,
        ready_to_export=verdict in ("approved", "review"),
    )
    db.add(report)
    if project.state in (ProjectState.EDITING.value, ProjectState.GENERATING.value):
        approval_service.set_state(db, project, ProjectState.QC_REVIEW, note="qc run")
    db.flush()
    return report


AUTO_FIX_MAP = {
    "missing_cta": {"component": "cta", "action": "rerender_cta_only", "label_ar": "إضافة الدعوة وإعادة رسم طبقة CTA فقط"},
    "arabic_error": {"component": "captions", "action": "rerender_captions_only", "label_ar": "إعادة رسم الكابشن فقط"},
    "caption_contrast": {"component": "captions", "action": "rerender_captions_only", "label_ar": "رفع التباين وإعادة رسم الكابشن"},
    "wrong_phone_number": {"component": "brand", "action": "rerender_brand_layer", "label_ar": "تصحيح الرقم بطبقة الهوية"},
    "voice_pronunciation": {"component": "voice", "action": "regenerate_voice_line", "label_ar": "إعادة توليد جملة الصوت فقط"},
    "product_distortion": {"component": "scene", "action": "regenerate_scene", "label_ar": "إعادة توليد المشهد المتأثر فقط"},
    "music_too_loud": {"component": "audio", "action": "remix_audio", "label_ar": "إعادة مزج الصوت فقط"},
    "hook_tighten": {"component": "timeline", "action": "retime_hook", "label_ar": "تقصير الخطّاف بدون إعادة توليد"},
    "wrong_project_name": {"component": "captions", "action": "rerender_captions_only", "label_ar": "إضافة اسم المشروع للكابشن"},
}


def auto_fix_plan(report: QCReport) -> List[Dict[str, Any]]:
    """Fix only the affected component — never regenerate everything."""
    plan: List[Dict[str, Any]] = []
    for item in (report.critical_issues or []) + (report.recommendations or []):
        mapping = AUTO_FIX_MAP.get(item.get("code", ""))
        if mapping:
            plan.append({**mapping, "code": item["code"], "message_ar": item.get("message_ar", "")})
    return plan


def apply_auto_fix(db: Session, project: Project, report: QCReport) -> Dict[str, Any]:
    """Apply component-scoped fixes and re-run QC."""
    plan = auto_fix_plan(report)
    applied: List[str] = []
    settings_changes: Dict[str, Any] = {}
    for step in plan:
        if step["component"] == "captions":
            settings_changes["captions_enabled"] = True
            settings_changes["caption_template"] = "bold_bar"
        elif step["component"] == "cta":
            settings_changes["cta_enabled"] = True
        elif step["component"] == "audio":
            settings_changes["music_volume"] = 0.16
            settings_changes["duck_music_under_voice"] = True
        elif step["component"] == "brand":
            settings_changes["branding_enabled"] = True
        applied.append(step["action"])

    if settings_changes:
        from app.services.editing import update_edit_settings

        update_edit_settings(db, project, settings_changes)
    if not project.cta:
        project.cta = "اتصل بينا اليوم"
    db.flush()

    from app.services.editing import render_project

    render = render_project(db, project)
    new_report = run_qc(db, project, render=render)
    return {"applied": applied, "report_id": new_report.id, "total_score": new_report.total_score, "verdict": new_report.verdict}


def qc_payload(report: QCReport) -> Dict[str, Any]:
    return {
        "id": report.id,
        "version": report.version,
        "render_id": report.render_id,
        "scores": report.scores,
        "weights": WEIGHTS,
        "total_score": report.total_score,
        "verdict": report.verdict,
        "critical_issues": report.critical_issues,
        "recommendations": report.recommendations,
        "checks": report.checks,
        "ready_to_export": report.ready_to_export,
        "auto_fix_plan": auto_fix_plan(report),
        "thresholds": {"approve": settings.QC_APPROVE_THRESHOLD, "review": settings.QC_REVIEW_THRESHOLD},
    }
