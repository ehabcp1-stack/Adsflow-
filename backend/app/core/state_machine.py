"""Official AdFlow AI project state machine.

Rules:
  * Transitions must be validated — an invalid transition raises.
  * A stage may not run unless the prerequisite approval exists.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Set

from app.core.enums import ApprovalEntity, ProjectState, WorkflowStage

S = ProjectState

#: Allowed forward/backward transitions.
TRANSITIONS: Dict[ProjectState, Set[ProjectState]] = {
    S.DRAFT: {S.ANALYZING, S.CANCELLED, S.PAUSED},
    S.ANALYZING: {S.ANALYSIS_READY, S.FAILED, S.DRAFT, S.CANCELLED},
    S.ANALYSIS_READY: {S.CONCEPT_REVIEW, S.ANALYZING, S.DRAFT, S.PAUSED, S.CANCELLED},
    S.CONCEPT_REVIEW: {S.CONCEPT_APPROVED, S.ANALYSIS_READY, S.PAUSED, S.CANCELLED, S.FAILED},
    S.CONCEPT_APPROVED: {S.SCRIPT_REVIEW, S.CONCEPT_REVIEW, S.PAUSED, S.CANCELLED},
    S.SCRIPT_REVIEW: {S.SCRIPT_APPROVED, S.CONCEPT_APPROVED, S.CONCEPT_REVIEW, S.PAUSED, S.CANCELLED},
    S.SCRIPT_APPROVED: {S.STORYBOARD_REVIEW, S.SCRIPT_REVIEW, S.PAUSED, S.CANCELLED},
    S.STORYBOARD_REVIEW: {S.STORYBOARD_APPROVED, S.SCRIPT_APPROVED, S.SCRIPT_REVIEW, S.PAUSED, S.CANCELLED},
    S.STORYBOARD_APPROVED: {S.PRODUCTION_READY, S.STORYBOARD_REVIEW, S.PAUSED, S.CANCELLED},
    S.PRODUCTION_READY: {S.GENERATING, S.STORYBOARD_REVIEW, S.PAUSED, S.CANCELLED},
    S.GENERATING: {S.EDITING, S.FAILED, S.PAUSED, S.CANCELLED, S.PRODUCTION_READY},
    S.EDITING: {S.QC_REVIEW, S.GENERATING, S.PAUSED, S.CANCELLED},
    S.QC_REVIEW: {S.FINAL_APPROVAL, S.EDITING, S.GENERATING, S.PAUSED, S.CANCELLED},
    S.FINAL_APPROVAL: {S.EXPORTED, S.QC_REVIEW, S.EDITING, S.PAUSED, S.CANCELLED},
    S.EXPORTED: {S.EDITING, S.QC_REVIEW, S.DRAFT},
    S.PAUSED: set(S) - {S.PAUSED},
    S.FAILED: {S.DRAFT, S.ANALYZING, S.PRODUCTION_READY, S.EDITING, S.CANCELLED, S.PAUSED},
    S.CANCELLED: {S.DRAFT},
}

#: Which approval must exist before a stage may run.
STAGE_PREREQUISITE_APPROVAL: Dict[WorkflowStage, Optional[ApprovalEntity]] = {
    WorkflowStage.BRIEF: None,
    WorkflowStage.ANALYZE: None,
    WorkflowStage.CONCEPTS: ApprovalEntity.ANALYSIS,
    WorkflowStage.SCRIPT: ApprovalEntity.CONCEPT,
    WorkflowStage.VOICE: ApprovalEntity.SCRIPT,
    WorkflowStage.STORYBOARD: ApprovalEntity.SCRIPT,
    WorkflowStage.PRODUCTION: ApprovalEntity.STORYBOARD,
    WorkflowStage.EDIT: ApprovalEntity.PRODUCTION_PLAN,
    WorkflowStage.QC: ApprovalEntity.PRODUCTION_PLAN,
    WorkflowStage.EXPORT: ApprovalEntity.FINAL,
}

#: Downstream approvals invalidated when an upstream artifact changes.
DOWNSTREAM_DEPENDENCIES: Dict[ApprovalEntity, List[ApprovalEntity]] = {
    ApprovalEntity.ANALYSIS: [
        ApprovalEntity.CONCEPT,
        ApprovalEntity.SCRIPT,
        ApprovalEntity.VOICE,
        ApprovalEntity.STORYBOARD,
        ApprovalEntity.PRODUCTION_PLAN,
        ApprovalEntity.FINAL,
    ],
    ApprovalEntity.CONCEPT: [
        ApprovalEntity.SCRIPT,
        ApprovalEntity.VOICE,
        ApprovalEntity.STORYBOARD,
        ApprovalEntity.PRODUCTION_PLAN,
        ApprovalEntity.FINAL,
    ],
    ApprovalEntity.SCRIPT: [
        ApprovalEntity.VOICE,
        ApprovalEntity.STORYBOARD,
        ApprovalEntity.PRODUCTION_PLAN,
        ApprovalEntity.FINAL,
    ],
    ApprovalEntity.VOICE: [ApprovalEntity.STORYBOARD, ApprovalEntity.PRODUCTION_PLAN, ApprovalEntity.FINAL],
    ApprovalEntity.STORYBOARD: [ApprovalEntity.PRODUCTION_PLAN, ApprovalEntity.FINAL],
    ApprovalEntity.PRODUCTION_PLAN: [ApprovalEntity.FINAL],
    ApprovalEntity.BUDGET: [ApprovalEntity.FINAL],
    ApprovalEntity.FINAL: [],
}

#: State reached when a stage's artifact is approved.
STATE_AFTER_APPROVAL: Dict[ApprovalEntity, ProjectState] = {
    ApprovalEntity.ANALYSIS: S.CONCEPT_REVIEW,
    ApprovalEntity.CONCEPT: S.CONCEPT_APPROVED,
    ApprovalEntity.SCRIPT: S.SCRIPT_APPROVED,
    ApprovalEntity.VOICE: S.SCRIPT_APPROVED,
    ApprovalEntity.STORYBOARD: S.STORYBOARD_APPROVED,
    ApprovalEntity.PRODUCTION_PLAN: S.PRODUCTION_READY,
    ApprovalEntity.FINAL: S.FINAL_APPROVAL,
}

#: State a project returns to when a downstream approval is invalidated.
STATE_ON_INVALIDATION: Dict[ApprovalEntity, ProjectState] = {
    ApprovalEntity.CONCEPT: S.CONCEPT_REVIEW,
    ApprovalEntity.SCRIPT: S.SCRIPT_REVIEW,
    ApprovalEntity.VOICE: S.SCRIPT_REVIEW,
    ApprovalEntity.STORYBOARD: S.STORYBOARD_REVIEW,
    ApprovalEntity.PRODUCTION_PLAN: S.STORYBOARD_REVIEW,
    ApprovalEntity.FINAL: S.QC_REVIEW,
}

STAGE_ORDER: List[WorkflowStage] = [
    WorkflowStage.BRIEF,
    WorkflowStage.ANALYZE,
    WorkflowStage.CONCEPTS,
    WorkflowStage.SCRIPT,
    WorkflowStage.VOICE,
    WorkflowStage.STORYBOARD,
    WorkflowStage.PRODUCTION,
    WorkflowStage.EDIT,
    WorkflowStage.QC,
    WorkflowStage.EXPORT,
]

#: Where a project sits in the visual stepper for a given state.
STATE_TO_STAGE: Dict[ProjectState, WorkflowStage] = {
    S.DRAFT: WorkflowStage.BRIEF,
    S.ANALYZING: WorkflowStage.ANALYZE,
    S.ANALYSIS_READY: WorkflowStage.ANALYZE,
    S.CONCEPT_REVIEW: WorkflowStage.CONCEPTS,
    S.CONCEPT_APPROVED: WorkflowStage.SCRIPT,
    S.SCRIPT_REVIEW: WorkflowStage.SCRIPT,
    S.SCRIPT_APPROVED: WorkflowStage.VOICE,
    S.STORYBOARD_REVIEW: WorkflowStage.STORYBOARD,
    S.STORYBOARD_APPROVED: WorkflowStage.PRODUCTION,
    S.PRODUCTION_READY: WorkflowStage.PRODUCTION,
    S.GENERATING: WorkflowStage.PRODUCTION,
    S.EDITING: WorkflowStage.EDIT,
    S.QC_REVIEW: WorkflowStage.QC,
    S.FINAL_APPROVAL: WorkflowStage.QC,
    S.EXPORTED: WorkflowStage.EXPORT,
    S.PAUSED: WorkflowStage.BRIEF,
    S.FAILED: WorkflowStage.BRIEF,
    S.CANCELLED: WorkflowStage.BRIEF,
}


class InvalidTransition(Exception):
    def __init__(self, current: ProjectState, target: ProjectState):
        self.current, self.target = current, target
        super().__init__(f"Invalid project transition {current} -> {target}")


class ApprovalRequired(Exception):
    def __init__(self, stage: WorkflowStage, entity: ApprovalEntity):
        self.stage, self.entity = stage, entity
        super().__init__(f"Stage '{stage}' requires an approved '{entity}' first")


def can_transition(current: ProjectState, target: ProjectState) -> bool:
    if current == target:
        return True
    return target in TRANSITIONS.get(current, set())


def assert_transition(current: ProjectState, target: ProjectState) -> ProjectState:
    if not can_transition(current, target):
        raise InvalidTransition(current, target)
    return target


def prerequisite_for(stage: WorkflowStage) -> Optional[ApprovalEntity]:
    return STAGE_PREREQUISITE_APPROVAL.get(stage)


def downstream_of(entity: ApprovalEntity) -> List[ApprovalEntity]:
    return DOWNSTREAM_DEPENDENCIES.get(entity, [])
