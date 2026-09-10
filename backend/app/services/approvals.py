"""Approval system + downstream invalidation.

If an upstream approved artifact changes, dependent downstream approvals are
invalidated and the project returns to the matching review state.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.enums import ApprovalEntity, ApprovalStatus, ProjectState, WorkflowStage
from app.core.errors import ApprovalMissing
from app.core import state_machine as sm
from app.models import Approval, Project


def latest_approval(db: Session, project_id: str, entity: str) -> Optional[Approval]:
    return (
        db.query(Approval)
        .filter(Approval.project_id == project_id, Approval.entity_type == entity)
        .order_by(Approval.created_at.desc())
        .first()
    )


def is_approved(db: Session, project_id: str, entity: str) -> bool:
    approval = latest_approval(db, project_id, entity)
    return bool(approval and approval.status == ApprovalStatus.APPROVED.value)


def require_approval(db: Session, project: Project, stage: WorkflowStage) -> None:
    entity = sm.prerequisite_for(stage)
    if entity is None:
        return
    if not is_approved(db, project.id, entity.value):
        raise ApprovalMissing(
            f"Stage '{stage.value}' needs an approved {entity.value} first.",
            f"لازم توافق على «{entity.value}» قبل مرحلة «{stage.value}».",
            stage=stage.value,
            required_entity=entity.value,
        )


def approve(
    db: Session,
    *,
    project: Project,
    entity: ApprovalEntity | str,
    entity_id: Optional[str] = None,
    version: int = 1,
    user_id: Optional[str] = None,
    notes: str = "",
) -> Approval:
    entity_value = entity.value if isinstance(entity, ApprovalEntity) else entity
    approval = Approval(
        project_id=project.id,
        entity_type=entity_value,
        entity_id=entity_id,
        version=version,
        status=ApprovalStatus.APPROVED.value,
        approved_by_id=user_id,
        approved_at=utcnow(),
        notes=notes,
    )
    db.add(approval)
    db.flush()
    return approval


def invalidate_downstream(
    db: Session, *, project: Project, changed_entity: ApprovalEntity | str, reason: str = ""
) -> List[str]:
    """Invalidate approvals that depended on the changed artifact."""
    entity = ApprovalEntity(changed_entity) if isinstance(changed_entity, str) else changed_entity
    invalidated: List[str] = []
    lowest_state: Optional[ProjectState] = None

    for downstream in sm.downstream_of(entity):
        approval = latest_approval(db, project.id, downstream.value)
        if approval and approval.status == ApprovalStatus.APPROVED.value:
            approval.status = ApprovalStatus.INVALIDATED.value
            approval.invalidated_reason = reason or f"{entity.value} changed after approval"
            invalidated.append(downstream.value)
            target = sm.STATE_ON_INVALIDATION.get(downstream)
            if target and (lowest_state is None or _stage_index(target) < _stage_index(lowest_state)):
                lowest_state = target

    if lowest_state and sm.can_transition(ProjectState(project.state), lowest_state):
        set_state(db, project, lowest_state, note=f"downstream invalidation after {entity.value} change")
    db.flush()
    return invalidated


def _stage_index(state: ProjectState) -> int:
    stage = sm.STATE_TO_STAGE.get(state, WorkflowStage.BRIEF)
    return sm.STAGE_ORDER.index(stage)


def set_state(db: Session, project: Project, target: ProjectState, note: str = "") -> Project:
    from app.core.errors import InvalidStateTransition

    current = ProjectState(project.state)
    if not sm.can_transition(current, target):
        raise InvalidStateTransition(
            f"Cannot move project from {current.value} to {target.value}.",
            f"ما نكدر ننقل المشروع من {current.value} إلى {target.value}.",
            current_state=current.value,
            target_state=target.value,
        )
    history = list(project.state_history or [])
    history.append({"from": current.value, "to": target.value, "at": utcnow().isoformat(), "note": note})
    project.state_history = history
    project.state = target.value
    db.flush()
    return project


def approvals_summary(db: Session, project: Project) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for entity in ApprovalEntity:
        approval = latest_approval(db, project.id, entity.value)
        out[entity.value] = {
            "status": approval.status if approval else ApprovalStatus.PENDING.value,
            "version": approval.version if approval else 0,
            "approved_at": approval.approved_at.isoformat() if approval and approval.approved_at else None,
            "entity_id": approval.entity_id if approval else None,
        }
    return out
