"""Project state transitions must be validated."""
from __future__ import annotations

import pytest

from app.core.enums import ProjectState as S
from app.core.errors import InvalidStateTransition
from app.core.state_machine import (
    STAGE_ORDER,
    STATE_TO_STAGE,
    InvalidTransition,
    assert_transition,
    can_transition,
)
from app.services.approvals import set_state


def test_forward_path_is_allowed():
    path = [
        S.DRAFT, S.ANALYZING, S.ANALYSIS_READY, S.CONCEPT_REVIEW, S.CONCEPT_APPROVED,
        S.SCRIPT_REVIEW, S.SCRIPT_APPROVED, S.STORYBOARD_REVIEW, S.STORYBOARD_APPROVED,
        S.PRODUCTION_READY, S.GENERATING, S.EDITING, S.QC_REVIEW, S.FINAL_APPROVAL, S.EXPORTED,
    ]
    for current, target in zip(path, path[1:]):
        assert can_transition(current, target), f"{current} -> {target} should be allowed"


def test_illegal_skips_are_rejected():
    assert not can_transition(S.DRAFT, S.EXPORTED)
    assert not can_transition(S.DRAFT, S.GENERATING)
    assert not can_transition(S.ANALYSIS_READY, S.PRODUCTION_READY)
    with pytest.raises(InvalidTransition):
        assert_transition(S.DRAFT, S.QC_REVIEW)


def test_supporting_states():
    assert can_transition(S.GENERATING, S.FAILED)
    assert can_transition(S.PAUSED, S.EDITING)
    assert can_transition(S.CANCELLED, S.DRAFT)


def test_every_state_maps_to_a_stage():
    for state in S:
        assert STATE_TO_STAGE[state] in STAGE_ORDER


def test_set_state_rejects_invalid_transition(db, make_project):
    project = make_project()
    with pytest.raises(InvalidStateTransition):
        set_state(db, project, S.EXPORTED)
    assert project.state == S.DRAFT.value


def test_set_state_records_history(db, make_project):
    project = make_project()
    set_state(db, project, S.ANALYZING, note="test")
    db.commit()
    assert project.state == S.ANALYZING.value
    assert project.state_history[-1]["to"] == S.ANALYZING.value
    assert project.state_history[-1]["note"] == "test"
