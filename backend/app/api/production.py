"""Production plan & approval, generation, editing, QC, export."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_project
from app.core.db import get_db
from app.core.enums import ApprovalEntity, ProjectState, WorkflowStage
from app.core.errors import NotFound
from app.core.security import get_current_user
from app.models import Project, QCReport, Scene, User
from app.schemas import ApproveRequest, EditSettingsUpdate, ExportRequest, LockRequest
from app.services import approvals as approval_service
from app.services import costs as cost_service
from app.services import editing as editing_service
from app.services import exports as export_service
from app.services import production as production_service
from app.services import qc as qc_service
from app.services import storyboards as storyboard_service
from app.services.director import notes_for_stage

router = APIRouter(prefix="/projects/{project_id}", tags=["production"])


# --------------------------------------------------------------------------
# Production plan
# --------------------------------------------------------------------------
@router.get("/production")
def get_production(project: Project = Depends(get_project), db: Session = Depends(get_db)) -> Dict[str, Any]:
    storyboard = storyboard_service.active_storyboard(db, project)
    return {
        "plan": storyboard.production_plan if storyboard else None,
        "budget": cost_service.budget_snapshot(db, project),
        "status": production_service.production_status(db, project) if storyboard else None,
        "approvals": approval_service.approvals_summary(db, project),
        "state": project.state,
    }


@router.post("/production/approve")
def approve_production(
    payload: Optional[ApproveRequest] = None,
    project: Project = Depends(get_project),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    payload = payload or ApproveRequest()
    approval_service.require_approval(db, project, WorkflowStage.PRODUCTION)
    storyboard = storyboard_service.active_storyboard(db, project)
    if not storyboard:
        raise NotFound("No production plan.", "ما أكو خطة إنتاج.")
    plan = storyboard.production_plan or {}
    if plan.get("status") == "budget_approval_required":
        cost_service.check_can_spend(db, project, plan.get("estimated_total_usd", 0), operation="production plan")
    approval_service.approve(
        db, project=project, entity=ApprovalEntity.PRODUCTION_PLAN, entity_id=storyboard.id,
        version=storyboard.version, user_id=user.id, notes=payload.notes,
    )
    approval_service.set_state(db, project, ProjectState.PRODUCTION_READY, note="production plan approved")
    db.commit()
    return {"ok": True, "state": project.state}


@router.post("/production/start")
def start_production(
    project: Project = Depends(get_project), db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    jobs = production_service.start_production(db, project, user_id=user.id)
    return {"ok": True, "jobs_created": len(jobs), "status": production_service.production_status(db, project)}


@router.get("/production/status")
def production_status(project: Project = Depends(get_project), db: Session = Depends(get_db)) -> Dict[str, Any]:
    return production_service.production_status(db, project)


@router.post("/production/finish")
def finish_production(project: Project = Depends(get_project), db: Session = Depends(get_db)) -> Dict[str, Any]:
    production_service.finish_production(db, project)
    db.commit()
    return {"ok": True, "state": project.state}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, project: Project = Depends(get_project),
               db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Cancel a queued or running job.

    The response is deliberately explicit about what cancellation did and did
    not stop — a job already handed to an external provider may have cost money
    that cancelling here cannot recover.
    """
    from app.models import GenerationJob
    from app.services.jobs import cancel_job as cancel

    job = db.get(GenerationJob, job_id)
    if not job or job.project_id != project.id:
        raise NotFound("Job not found.", "المهمة غير موجودة.")
    return cancel(db, job)


@router.post("/scenes/{scene_id}/regenerate")
def regenerate_scene(scene_id: str, project: Project = Depends(get_project), db: Session = Depends(get_db)) -> Dict[str, Any]:
    scene = db.get(Scene, scene_id)
    if not scene:
        raise NotFound("Scene not found.", "المشهد غير موجود.")
    job = production_service.regenerate_scene(db, project, scene)
    return {"ok": True, "job_id": job.id}


@router.post("/scenes/{scene_id}/approve")
def approve_scene(
    scene_id: str, payload: Optional[LockRequest] = None, project: Project = Depends(get_project), db: Session = Depends(get_db)
) -> Dict[str, Any]:
    payload = payload or LockRequest(locked=False)
    scene = db.get(Scene, scene_id)
    if not scene:
        raise NotFound("Scene not found.", "المشهد غير موجود.")
    production_service.approve_scene(db, scene, lock=payload.locked)
    db.commit()
    return storyboard_service.scene_payload(scene)


# --------------------------------------------------------------------------
# Editing
# --------------------------------------------------------------------------
@router.get("/edit")
def get_edit(project: Project = Depends(get_project), db: Session = Depends(get_db)) -> Dict[str, Any]:
    render = editing_service.active_render(db, project)
    storyboard = storyboard_service.active_storyboard(db, project)
    return {
        "render": editing_service.render_payload(render) if render else None,
        "styles": editing_service.EDITING_STYLES,
        "caption_templates": editing_service.CAPTION_TEMPLATES,
        "remix_operations": editing_service.REMIX_OPERATIONS,
        "settings": {**editing_service.DEFAULT_EDIT_SETTINGS, **(project.edit_settings or {})},
        "editing_style": project.editing_style,
        "recommended_style": editing_service.recommend_style(project),
        "scenes": [storyboard_service.scene_payload(s) for s in sorted(storyboard.scenes, key=lambda s: s.scene_number)]
        if storyboard
        else [],
        "director_notes": notes_for_stage(db, project, WorkflowStage.EDIT),
        "state": project.state,
    }


@router.post("/edit/settings")
def update_edit_settings(
    payload: EditSettingsUpdate, project: Project = Depends(get_project), db: Session = Depends(get_db)
) -> Dict[str, Any]:
    editing_service.update_edit_settings(db, project, payload.changes)
    db.commit()
    return get_edit(project=project, db=db)


@router.post("/edit/render")
def render(project: Project = Depends(get_project), db: Session = Depends(get_db)) -> Dict[str, Any]:
    render = editing_service.render_project(db, project)
    db.commit()
    return editing_service.render_payload(render)


# --------------------------------------------------------------------------
# QC
# --------------------------------------------------------------------------
@router.get("/qc")
def get_qc(project: Project = Depends(get_project), db: Session = Depends(get_db)) -> Dict[str, Any]:
    report = (
        db.query(QCReport).filter(QCReport.project_id == project.id).order_by(QCReport.version.desc()).first()
    )
    return {
        "report": qc_service.qc_payload(report) if report else None,
        "levels": qc_service.QC_LEVELS,
        "weights": qc_service.WEIGHTS,
        "state": project.state,
    }


@router.post("/qc/run")
def run_qc(project: Project = Depends(get_project), db: Session = Depends(get_db)) -> Dict[str, Any]:
    if not editing_service.active_render(db, project):
        editing_service.render_project(db, project)
    report = qc_service.run_qc(db, project)
    db.commit()
    return qc_service.qc_payload(report)


@router.post("/qc/auto-fix")
def auto_fix(project: Project = Depends(get_project), db: Session = Depends(get_db)) -> Dict[str, Any]:
    report = (
        db.query(QCReport).filter(QCReport.project_id == project.id).order_by(QCReport.version.desc()).first()
    )
    if not report:
        raise NotFound("Run QC first.", "شغّل الفحص أول.")
    result = qc_service.apply_auto_fix(db, project, report)
    db.commit()
    return result


@router.post("/qc/approve")
def approve_final(
    payload: Optional[ApproveRequest] = None,
    project: Project = Depends(get_project),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    payload = payload or ApproveRequest()
    report = (
        db.query(QCReport).filter(QCReport.project_id == project.id).order_by(QCReport.version.desc()).first()
    )
    approval_service.approve(
        db, project=project, entity=ApprovalEntity.FINAL, entity_id=report.id if report else None,
        version=report.version if report else 1, user_id=user.id, notes=payload.notes,
    )
    approval_service.set_state(db, project, ProjectState.FINAL_APPROVAL, note="final approved")
    db.commit()
    return {"ok": True, "state": project.state}


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------
@router.get("/export")
def get_exports(project: Project = Depends(get_project), db: Session = Depends(get_db)) -> Dict[str, Any]:
    render = editing_service.active_render(db, project)
    report = (
        db.query(QCReport).filter(QCReport.project_id == project.id).order_by(QCReport.version.desc()).first()
    )
    return {
        "variants": export_service.VARIANTS,
        "ratios": list(export_service.RATIOS.keys()),
        "items": [
            export_service.export_payload(e)
            for e in sorted(project.exports, key=lambda e: e.created_at or 0, reverse=True)
        ],
        "render": editing_service.render_payload(render) if render else None,
        "qc": {"total_score": report.total_score, "verdict": report.verdict, "ready": report.ready_to_export}
        if report
        else None,
        "state": project.state,
    }


@router.post("/export")
def create_export(
    payload: Optional[ExportRequest] = None,
    project: Project = Depends(get_project),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    payload = payload or ExportRequest()
    export = export_service.create_export(
        db, project, variant=payload.variant, aspect_ratio=payload.aspect_ratio, force=payload.force, user_id=user.id
    )
    db.commit()
    return export_service.export_payload(export)
