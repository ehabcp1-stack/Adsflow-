"""Budget Guard + Cost Ledger."""
from __future__ import annotations

import pytest

from app.core.enums import CostStatus
from app.core.errors import BudgetExceeded
from app.services import costs as cost_service


def test_cheap_action_passes(db, make_project):
    project = make_project(budget_limit_usd=10.0)
    cost_service.check_can_spend(db, project, 2.5)  # no raise


def test_expensive_action_is_blocked(db, make_project):
    project = make_project(budget_limit_usd=3.0)
    with pytest.raises(BudgetExceeded) as exc:
        cost_service.check_can_spend(db, project, 9.0, operation="video generation")
    payload = exc.value.to_payload()["error"]
    assert payload["code"] == "budget_exceeded"
    assert payload["required_usd"] == 9.0
    assert payload["message_ar"]


def test_reserved_then_actual_updates_totals(db, make_project):
    project = make_project(budget_limit_usd=10.0)
    cost_service.record_cost(
        db, project=project, provider="mock", model="mock-video-v1", operation="video_generation",
        estimated=1.5, status=CostStatus.RESERVED.value,
    )
    db.commit()
    snapshot = cost_service.budget_snapshot(db, project)
    assert snapshot["reserved_cost_usd"] == 1.5
    assert snapshot["remaining_budget_usd"] == 8.5

    cost_service.record_cost(
        db, project=project, provider="mock", model="mock-video-v1", operation="video_generation",
        estimated=1.5, actual=1.2, status=CostStatus.ACTUAL.value,
    )
    db.commit()
    snapshot = cost_service.budget_snapshot(db, project)
    assert snapshot["actual_cost_usd"] == 1.2
    assert project.actual_cost_usd == 1.2


def test_reserved_spend_reduces_headroom(db, make_project):
    project = make_project(budget_limit_usd=5.0)
    cost_service.record_cost(
        db, project=project, provider="mock", model="m", operation="op",
        estimated=4.5, status=CostStatus.RESERVED.value,
    )
    db.commit()
    with pytest.raises(BudgetExceeded):
        cost_service.check_can_spend(db, project, 1.0)


def test_breakdown_groups_by_operation(db, make_project):
    project = make_project()
    for op, value in (("voice_generation", 0.2), ("image_generation", 0.4), ("image_generation", 0.4)):
        cost_service.record_cost(
            db, project=project, provider="mock", model="m", operation=op, actual=value,
            status=CostStatus.ACTUAL.value,
        )
    db.commit()
    breakdown = cost_service.cost_breakdown(db, project)
    assert breakdown["by_operation"]["image_generation"] == 0.8
    assert breakdown["by_operation"]["voice_generation"] == 0.2


def test_zero_cost_never_blocks(db, make_project):
    project = make_project(budget_limit_usd=0.0)
    cost_service.check_can_spend(db, project, 0.0)
