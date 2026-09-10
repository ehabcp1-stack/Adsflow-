"""Approval gates and downstream invalidation."""
from __future__ import annotations

import pytest

from app.core.enums import ApprovalEntity, ApprovalStatus, ProjectState, WorkflowStage
from app.core.errors import ApprovalMissing
from app.services import approvals as approval_service


def test_stage_requires_prerequisite_approval(db, make_project):
    project = make_project()
    with pytest.raises(ApprovalMissing):
        approval_service.require_approval(db, project, WorkflowStage.CONCEPTS)

    approval_service.approve(db, project=project, entity=ApprovalEntity.ANALYSIS)
    db.commit()
    approval_service.require_approval(db, project, WorkflowStage.CONCEPTS)  # no raise


def test_brief_stages_need_no_approval(db, make_project):
    project = make_project()
    approval_service.require_approval(db, project, WorkflowStage.BRIEF)
    approval_service.require_approval(db, project, WorkflowStage.ANALYZE)


def test_script_change_invalidates_storyboard_approval(db, make_project):
    project = make_project()
    for entity in (ApprovalEntity.ANALYSIS, ApprovalEntity.CONCEPT, ApprovalEntity.SCRIPT, ApprovalEntity.STORYBOARD):
        approval_service.approve(db, project=project, entity=entity)
    project.state = ProjectState.STORYBOARD_APPROVED.value
    db.commit()

    invalidated = approval_service.invalidate_downstream(
        db, project=project, changed_entity=ApprovalEntity.SCRIPT, reason="script edited"
    )
    db.commit()

    assert ApprovalEntity.STORYBOARD.value in invalidated
    assert not approval_service.is_approved(db, project.id, ApprovalEntity.STORYBOARD.value)
    # Upstream approvals survive.
    assert approval_service.is_approved(db, project.id, ApprovalEntity.CONCEPT.value)
    # Project returns to the storyboard review state.
    assert project.state == ProjectState.STORYBOARD_REVIEW.value


def test_invalidation_marks_status(db, make_project):
    project = make_project()
    approval_service.approve(db, project=project, entity=ApprovalEntity.SCRIPT)
    approval_service.approve(db, project=project, entity=ApprovalEntity.STORYBOARD)
    project.state = ProjectState.STORYBOARD_APPROVED.value
    db.commit()
    approval_service.invalidate_downstream(db, project=project, changed_entity=ApprovalEntity.SCRIPT)
    db.commit()
    record = approval_service.latest_approval(db, project.id, ApprovalEntity.STORYBOARD.value)
    assert record.status == ApprovalStatus.INVALIDATED.value
    assert record.invalidated_reason


def test_summary_lists_every_entity(db, make_project):
    project = make_project()
    summary = approval_service.approvals_summary(db, project)
    assert set(summary) == {entity.value for entity in ApprovalEntity}
    assert summary[ApprovalEntity.FINAL.value]["status"] == ApprovalStatus.PENDING.value
