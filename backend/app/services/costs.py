"""Cost Ledger + Budget Guard.

MANDATORY: no paid provider action may run without a cost check first.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import CostStatus
from app.core.errors import BudgetExceeded
from app.models import CostEntry, Project


def record_cost(
    db: Session,
    *,
    project: Project,
    provider: str,
    model: str,
    operation: str,
    estimated: float = 0.0,
    actual: float = 0.0,
    status: str = CostStatus.ESTIMATED.value,
    scene_id: Optional[str] = None,
    job_id: Optional[str] = None,
    is_mock: bool = True,
    note: str = "",
) -> CostEntry:
    entry = CostEntry(
        project_id=project.id,
        scene_id=scene_id,
        job_id=job_id,
        provider=provider,
        model=model,
        operation=operation,
        estimated_cost_usd=round(estimated, 4),
        actual_cost_usd=round(actual, 4),
        status=status,
        is_mock=is_mock,
        note=note,
    )
    db.add(entry)
    if status == CostStatus.ACTUAL.value:
        project.actual_cost_usd = round(project.actual_cost_usd + actual, 4)
        project.reserved_cost_usd = round(max(project.reserved_cost_usd - estimated, 0.0), 4)
    elif status == CostStatus.RESERVED.value:
        project.reserved_cost_usd = round(project.reserved_cost_usd + estimated, 4)
    db.flush()
    return entry


def budget_snapshot(db: Session, project: Project) -> Dict[str, Any]:
    entries: List[CostEntry] = db.query(CostEntry).filter(CostEntry.project_id == project.id).all()
    spent = round(sum(e.actual_cost_usd for e in entries), 4)
    reserved = round(sum(e.estimated_cost_usd for e in entries if e.status == CostStatus.RESERVED.value), 4)
    estimated = round(project.estimated_cost_usd, 4)
    reserve = round(estimated * settings.REGENERATION_RESERVE_RATIO, 4)
    remaining = round(project.budget_limit_usd - spent - reserved, 4)
    return {
        "budget_limit_usd": round(project.budget_limit_usd, 4),
        "estimated_cost_usd": estimated,
        "actual_cost_usd": spent,
        "reserved_cost_usd": reserved,
        "regeneration_reserve_usd": reserve,
        "remaining_budget_usd": remaining,
        "over_budget": estimated + reserve > project.budget_limit_usd,
        "status": "budget_approval_required" if estimated + reserve > project.budget_limit_usd else "safe_to_generate",
        "entries": len(entries),
    }


def check_can_spend(db: Session, project: Project, amount: float, *, operation: str = "generation") -> None:
    """Raise BudgetExceeded when a paid action would exceed the project budget."""
    if amount <= 0:
        return
    snapshot = budget_snapshot(db, project)
    if amount > snapshot["remaining_budget_usd"]:
        raise BudgetExceeded(
            f"This {operation} costs ${amount:.2f} but only ${snapshot['remaining_budget_usd']:.2f} remains "
            f"of the ${project.budget_limit_usd:.2f} project budget. Approve a higher budget to continue.",
            f"هذه العملية تكلف ${amount:.2f} والمتبقي ${snapshot['remaining_budget_usd']:.2f} فقط من ميزانية "
            f"${project.budget_limit_usd:.2f}. تحتاج موافقة على ميزانية أعلى.",
            required_usd=round(amount, 4),
            remaining_usd=snapshot["remaining_budget_usd"],
            budget_limit_usd=snapshot["budget_limit_usd"],
        )


def cost_breakdown(db: Session, project: Project) -> Dict[str, Any]:
    by_operation: Dict[str, float] = {}
    by_scene: Dict[str, float] = {}
    for entry in db.query(CostEntry).filter(CostEntry.project_id == project.id).all():
        value = entry.actual_cost_usd or entry.estimated_cost_usd
        by_operation[entry.operation] = round(by_operation.get(entry.operation, 0.0) + value, 4)
        if entry.scene_id:
            by_scene[entry.scene_id] = round(by_scene.get(entry.scene_id, 0.0) + value, 4)
    return {"by_operation": by_operation, "by_scene": by_scene}


def monthly_spend(db: Session, organization_id: str) -> Dict[str, Any]:
    projects = db.query(Project).filter(Project.organization_id == organization_id).all()
    spent = round(sum(p.actual_cost_usd for p in projects), 2)
    return {
        "month_spend_usd": spent,
        "monthly_target_usd": settings.MONTHLY_BUDGET_TARGET_USD,
        "completed_videos": sum(1 for p in projects if p.state == "EXPORTED"),
        "active_projects": sum(1 for p in projects if p.state not in ("EXPORTED", "CANCELLED")),
    }
