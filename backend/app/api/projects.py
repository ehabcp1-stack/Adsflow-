"""Projects: dashboard, CRUD, brief wizard, state, budget, archive, duplicate."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_project
from app.core.config import settings
from app.core.db import get_db
from app.core.enums import ApprovalEntity, ProjectState
from app.core.security import get_current_user
from app.core.state_machine import STAGE_ORDER, STATE_TO_STAGE
from app.models import Asset, BrandKit, Project, User
from app.schemas import BudgetUpdate, ProjectCreate, ProjectUpdate
from app.services import approvals as approval_service
from app.services import costs as cost_service
from app.services.exports import project_archive
from app.services.storyboards import active_storyboard

router = APIRouter(tags=["projects"])


def project_summary(project: Project) -> Dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "category": project.category,
        "goal": project.goal,
        "platform": project.platform,
        "duration_sec": project.duration_sec,
        "language": project.language,
        "dialect": project.dialect,
        "tone": project.tone,
        "state": project.state,
        "stage": STATE_TO_STAGE.get(ProjectState(project.state), STAGE_ORDER[0]).value,
        "thumbnail_url": project.thumbnail_url,
        "estimated_cost_usd": project.estimated_cost_usd,
        "actual_cost_usd": project.actual_cost_usd,
        "budget_limit_usd": project.budget_limit_usd,
        "production_mode": project.production_mode,
        "quality_level": project.quality_level,
        "editing_style": project.editing_style,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "archived": project.archived,
    }


def project_detail(db: Session, project: Project) -> Dict[str, Any]:
    storyboard = active_storyboard(db, project)
    return {
        **project_summary(project),
        "target_audience": project.target_audience,
        "key_information": project.key_information,
        "cta": project.cta,
        "voice_over_enabled": project.voice_over_enabled,
        "brand_kit_id": project.brand_kit_id,
        "selected_concept_id": project.selected_concept_id,
        "selected_script_id": project.selected_script_id,
        "selected_voice_profile_id": project.selected_voice_profile_id,
        "voice_locked": project.voice_locked,
        "edit_settings": project.edit_settings,
        "architecture_fidelity_lock": project.architecture_fidelity_lock,
        "product_fidelity_lock": project.product_fidelity_lock,
        "state_history": project.state_history,
        "approvals": approval_service.approvals_summary(db, project),
        "budget": cost_service.budget_snapshot(db, project),
        "asset_count": db.query(Asset).filter(Asset.project_id == project.id).count(),
        "storyboard_id": storyboard.id if storyboard else None,
        "stages": [stage.value for stage in STAGE_ORDER],
    }


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Dict[str, Any]:
    projects = (
        db.query(Project)
        .filter(Project.organization_id == user.organization_id)
        .order_by(Project.updated_at.desc())
        .limit(8)
        .all()
    )
    spend = cost_service.monthly_spend(db, user.organization_id)
    return {
        "brand": {"product": settings.APP_NAME, "parent": settings.APP_BRAND_PARENT},
        "metrics": {
            "monthly_ai_spend_usd": spend["month_spend_usd"],
            "monthly_target_usd": spend["monthly_target_usd"],
            "completed_videos": spend["completed_videos"],
            "active_projects": spend["active_projects"],
        },
        "recent_projects": [project_summary(p) for p in projects],
    }


@router.get("/projects")
def list_projects(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    state: Optional[str] = Query(default=None),
    archived: bool = Query(default=False),
) -> Dict[str, Any]:
    query = db.query(Project).filter(
        Project.organization_id == user.organization_id, Project.archived.is_(archived)
    )
    if state:
        query = query.filter(Project.state == state)
    projects = query.order_by(Project.updated_at.desc()).all()
    return {"items": [project_summary(p) for p in projects], "total": len(projects)}


@router.post("/projects", status_code=201)
def create_project(
    payload: ProjectCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    brand_kit_id = payload.brand_kit_id
    if not brand_kit_id:
        default_kit = (
            db.query(BrandKit)
            .filter(BrandKit.organization_id == user.organization_id, BrandKit.is_default.is_(True))
            .first()
        )
        brand_kit_id = default_kit.id if default_kit else None

    project = Project(
        organization_id=user.organization_id,
        created_by_id=user.id,
        brand_kit_id=brand_kit_id,
        budget_limit_usd=payload.budget_limit_usd or settings.DEFAULT_PROJECT_BUDGET_USD,
        **payload.model_dump(exclude={"brand_kit_id", "budget_limit_usd", "asset_ids"}),
    )
    db.add(project)
    db.flush()

    for asset_id in payload.asset_ids:
        asset = db.get(Asset, asset_id)
        if asset and asset.organization_id == user.organization_id:
            asset.project_id = project.id
    db.commit()
    return project_detail(db, project)


@router.get("/projects/{project_id}")
def get_project_detail(project: Project = Depends(get_project), db: Session = Depends(get_db)) -> Dict[str, Any]:
    return project_detail(db, project)


@router.patch("/projects/{project_id}")
def update_project(
    payload: ProjectUpdate, project: Project = Depends(get_project), db: Session = Depends(get_db)
) -> Dict[str, Any]:
    changes = payload.model_dump(exclude_none=True)
    brief_fields = {
        "name", "category", "goal", "platform", "duration_sec", "language",
        "dialect", "tone", "target_audience", "key_information", "cta",
    }
    touched_brief = bool(brief_fields & set(changes))
    for field, value in changes.items():
        setattr(project, field, value)
    if touched_brief and project.state != ProjectState.DRAFT.value:
        approval_service.invalidate_downstream(
            db, project=project, changed_entity=ApprovalEntity.ANALYSIS, reason="brief changed"
        )
    db.commit()
    return project_detail(db, project)


@router.post("/projects/{project_id}/budget")
def update_budget(
    payload: BudgetUpdate, project: Project = Depends(get_project), db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    project.budget_limit_usd = round(payload.budget_limit_usd, 2)
    approval_service.approve(
        db, project=project, entity=ApprovalEntity.BUDGET, version=1, user_id=user.id,
        notes=f"budget raised to ${project.budget_limit_usd:.2f}",
    )
    db.commit()
    return cost_service.budget_snapshot(db, project)


@router.get("/projects/{project_id}/costs")
def project_costs(project: Project = Depends(get_project), db: Session = Depends(get_db)) -> Dict[str, Any]:
    return {
        **cost_service.budget_snapshot(db, project),
        **cost_service.cost_breakdown(db, project),
        "ledger": [
            {
                "id": e.id,
                "provider": e.provider,
                "model": e.model,
                "operation": e.operation,
                "estimated_cost_usd": e.estimated_cost_usd,
                "actual_cost_usd": e.actual_cost_usd,
                "status": e.status,
                "is_mock": e.is_mock,
                "scene_id": e.scene_id,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in sorted(project.cost_entries, key=lambda c: c.created_at or 0, reverse=True)
        ],
    }


@router.get("/projects/{project_id}/archive")
def get_archive(project: Project = Depends(get_project), db: Session = Depends(get_db)) -> Dict[str, Any]:
    return project_archive(db, project)


@router.post("/projects/{project_id}/duplicate", status_code=201)
def duplicate_project(
    project: Project = Depends(get_project), db: Session = Depends(get_db), user: User = Depends(get_current_user),
    new_version: bool = Query(default=False),
) -> Dict[str, Any]:
    clone = Project(
        organization_id=project.organization_id,
        created_by_id=user.id,
        brand_kit_id=project.brand_kit_id,
        name=f"{project.name} — {'نسخة جديدة' if new_version else 'نسخة'}",
        category=project.category,
        goal=project.goal,
        platform=project.platform,
        duration_sec=project.duration_sec,
        language=project.language,
        dialect=project.dialect,
        tone=project.tone,
        target_audience=project.target_audience,
        key_information=project.key_information,
        cta=project.cta,
        production_mode=project.production_mode,
        quality_level=project.quality_level,
        voice_over_enabled=project.voice_over_enabled,
        budget_limit_usd=project.budget_limit_usd,
        editing_style=project.editing_style,
        duplicated_from_id=project.id,
        state=ProjectState.DRAFT.value,
    )
    db.add(clone)
    db.flush()
    for asset in db.query(Asset).filter(Asset.project_id == project.id).all():
        db.add(
            Asset(
                organization_id=asset.organization_id,
                project_id=clone.id,
                kind=asset.kind,
                filename=asset.filename,
                storage_key=asset.storage_key,
                url=asset.url,
                thumbnail_url=asset.thumbnail_url,
                mime_type=asset.mime_type,
                size_bytes=asset.size_bytes,
                width=asset.width,
                height=asset.height,
                duration_sec=asset.duration_sec,
                orientation=asset.orientation,
                is_project_reference=asset.is_project_reference,
                tags=asset.tags,
            )
        )
    db.commit()
    return project_detail(db, clone)


@router.delete("/projects/{project_id}")
def archive_project(project: Project = Depends(get_project), db: Session = Depends(get_db)) -> Dict[str, Any]:
    project.archived = True
    db.commit()
    return {"ok": True, "id": project.id}


@router.get("/projects/{project_id}/jobs")
def project_jobs(project: Project = Depends(get_project)) -> Dict[str, Any]:
    from app.services.jobs import job_payload

    return {"items": [job_payload(j) for j in sorted(project.jobs, key=lambda j: j.created_at or 0, reverse=True)]}
