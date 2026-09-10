"""Export Engine.

Primary: 1080×1920 · 9:16 · MP4 · H.264
Naming: ProjectName_Concept_Version_Platform_Date
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.enums import AspectRatio, ExportVariant, ProjectState
from app.core.errors import NotFound
from app.models import Asset, Concept, Export, Project, QCReport, Render
from app.services import approvals as approval_service
from app.services.editing import active_render
from app.services.media_placeholder import save_frame
from app.services.storage import get_storage

VARIANTS: List[Dict[str, Any]] = [
    {"key": ExportVariant.MASTER.value, "label_en": "Master", "label_ar": "النسخة الرئيسية"},
    {"key": ExportVariant.WITH_CAPTIONS.value, "label_en": "With Captions", "label_ar": "مع كابشن"},
    {"key": ExportVariant.WITHOUT_CAPTIONS.value, "label_en": "Without Captions", "label_ar": "بدون كابشن"},
    {"key": ExportVariant.WITHOUT_MUSIC.value, "label_en": "Without Music", "label_ar": "بدون موسيقى"},
    {"key": ExportVariant.VOICE_ONLY.value, "label_en": "Voice Only", "label_ar": "صوت فقط"},
    {"key": ExportVariant.CLEAN_NO_LOGO.value, "label_en": "Clean (no logo)", "label_ar": "نظيفة بدون شعار"},
    {"key": ExportVariant.BRANDED.value, "label_en": "Branded", "label_ar": "نسخة بالهوية"},
    {"key": ExportVariant.THUMBNAIL.value, "label_en": "Thumbnail / Cover", "label_ar": "صورة الغلاف"},
]

RATIOS: Dict[str, tuple[int, int]] = {
    AspectRatio.VERTICAL_9_16.value: (1080, 1920),
    AspectRatio.SQUARE_1_1.value: (1080, 1080),
    AspectRatio.PORTRAIT_4_5.value: (1080, 1350),
    AspectRatio.LANDSCAPE_16_9.value: (1920, 1080),
}


def _slug(text: str) -> str:
    cleaned = re.sub(r"\s+", "-", (text or "").strip())
    return re.sub(r"[^\w\-؀-ۿ]", "", cleaned)[:40] or "AdFlow"


def build_filename(project: Project, concept: Optional[Concept], version: int, variant: str) -> str:
    parts = [
        _slug(project.name),
        _slug((concept.name_en or concept.name) if concept else "Concept"),
        f"v{version}",
        _slug(project.platform),
        date.today().isoformat(),
    ]
    suffix = "" if variant == ExportVariant.MASTER.value else f"_{variant}"
    ext = "png" if variant == ExportVariant.THUMBNAIL.value else "mp4"
    return f"{'_'.join(parts)}{suffix}.{ext}"


def create_export(
    db: Session,
    project: Project,
    *,
    variant: str = ExportVariant.MASTER.value,
    aspect_ratio: str = AspectRatio.VERTICAL_9_16.value,
    force: bool = False,
    user_id: Optional[str] = None,
) -> Export:
    render = active_render(db, project)
    if not render:
        raise NotFound("Nothing to export yet.", "ما أكو شي للتصدير.")

    report = db.query(QCReport).filter(QCReport.project_id == project.id).order_by(QCReport.version.desc()).first()
    if report and not report.ready_to_export and not force:
        from app.core.errors import QCFailed

        raise QCFailed(
            f"QC scored {report.total_score:.0f}/100 with unresolved critical issues. "
            "Fix them or export anyway.",
            f"نتيجة الفحص {report.total_score:.0f}/١٠٠ وأكو ملاحظات حرجة. صلّحها أو صدّر على أي حال.",
            total_score=report.total_score,
            verdict=report.verdict,
        )

    concept = db.get(Concept, project.selected_concept_id) if project.selected_concept_id else None
    width, height = RATIOS.get(aspect_ratio, (1080, 1920))
    filename = build_filename(project, concept, render.version, variant)

    if variant == ExportVariant.THUMBNAIL.value:
        url = save_frame(
            f"projects/{project.id}/exports/{filename.replace('.png', '.svg')}",
            seed=f"{project.id}-cover",
            title_ar=project.name,
            subtitle=(concept.name if concept else ""),
            badge="COVER",
            width=width,
            height=height,
        )
        size = 0
    else:
        url = render.url or render.poster_url
        storage = get_storage()
        size = 0
        if url and "/media/" in url:
            path = storage.local_path(url.split("/media/", 1)[-1])
            if path:
                try:
                    import os

                    size = os.path.getsize(path)
                except OSError:
                    size = 0

    export = Export(
        project_id=project.id,
        render_id=render.id,
        variant=variant,
        aspect_ratio=aspect_ratio,
        width=width,
        height=height,
        filename=filename,
        url=url,
        size_bytes=size,
        status="ready",
    )
    db.add(export)
    if project.state in (ProjectState.QC_REVIEW.value, ProjectState.FINAL_APPROVAL.value):
        if project.state == ProjectState.QC_REVIEW.value:
            approval_service.set_state(db, project, ProjectState.FINAL_APPROVAL, note="export requested")
        approval_service.set_state(db, project, ProjectState.EXPORTED, note=f"exported {variant}")
    db.flush()
    return export


def export_payload(export: Export) -> Dict[str, Any]:
    return {
        "id": export.id,
        "variant": export.variant,
        "aspect_ratio": export.aspect_ratio,
        "width": export.width,
        "height": export.height,
        "filename": export.filename,
        "url": export.url,
        "size_bytes": export.size_bytes,
        "codec": export.codec,
        "status": export.status,
        "created_at": export.created_at.isoformat() if export.created_at else None,
    }


def project_archive(db: Session, project: Project) -> Dict[str, Any]:
    """Everything preserved for 'Create New Reel From This Project'."""
    from app.services.concepts import concept_payload
    from app.services.editing import render_payload
    from app.services.qc import qc_payload
    from app.services.scripts import script_payload
    from app.services.storyboards import active_storyboard, storyboard_payload

    analysis = sorted(project.analyses, key=lambda a: -a.version)
    storyboard = active_storyboard(db, project)
    reports = sorted(project.qc_reports, key=lambda r: -r.version)
    return {
        "brief": {
            "name": project.name,
            "category": project.category,
            "goal": project.goal,
            "platform": project.platform,
            "duration_sec": project.duration_sec,
            "language": project.language,
            "dialect": project.dialect,
            "tone": project.tone,
            "target_audience": project.target_audience,
            "key_information": project.key_information,
            "cta": project.cta,
        },
        "analysis_versions": [{"version": a.version, "created_at": a.created_at.isoformat()} for a in analysis],
        "concepts": [concept_payload(c) for c in project.concepts],
        "approved_script": next(
            (script_payload(s) for s in project.scripts if s.is_selected), None
        ),
        "voice_profile_id": project.selected_voice_profile_id,
        "storyboard": storyboard_payload(db, storyboard) if storyboard else None,
        "assets": [
            {"id": a.id, "kind": a.kind, "url": a.url, "filename": a.filename}
            for a in db.query(Asset).filter(Asset.project_id == project.id).all()
        ],
        "renders": [render_payload(r) for r in sorted(project.renders, key=lambda r: -r.version)],
        "qc_reports": [qc_payload(r) for r in reports],
        "exports": [export_payload(e) for e in project.exports],
        "cost": {
            "estimated_usd": project.estimated_cost_usd,
            "actual_usd": project.actual_cost_usd,
            "budget_limit_usd": project.budget_limit_usd,
        },
        "qc_score": reports[0].total_score if reports else None,
    }
