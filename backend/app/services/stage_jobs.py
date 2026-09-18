"""The writing stages run as jobs. They never run inside an HTTP request.

Analysis, concepts, script and storyboard each call the LLM — script three
times, analysis twice. On mock providers every one of them returns in
milliseconds, which is why they sat inside their request handlers for months
and every test passed. Against the real writer a single call is tens of
seconds, and the first real deploy showed what that means: `POST
/analysis/run` ran for 42 seconds, the browser gave up with "ما نكدر نوصل
لسيرفر أدفلو", and `GET /analysis` afterwards reported no analysis at all.
The request was torn down mid-transaction, so the work was not merely unseen
— it was gone, and the money spent on it with it.

So each stage here is:

    POST .../generate   → create a job, commit, dispatch, return immediately
    GET  .../<stage>    → the artifact plus the job, which the client polls

Every `start_*` returns the job already in flight when there is one, so a
double-clicked button cannot become two sets of paid model calls.

CLAUDE.md §14: *long generation never blocks an HTTP request*.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.core.enums import JobType, ProjectState, WorkflowStage
from app.models import GenerationJob, Project
from app.services import approvals as approval_service
from app.services import concepts as concept_service
from app.services import scripts as script_service
from app.services import storyboards as storyboard_service
from app.services.analysis import run_analysis
from app.services.jobs import create_job, register_handler, set_progress


def latest_job(db: Session, project: Project, job_type: str) -> Optional[GenerationJob]:
    """This stage's most recent job — read *before* the rest of the payload.

    Call this first in a stage's GET handler, because it also expires the
    project so everything read afterwards is at least as new as the job status
    being reported.

    The reason is the gap between two SELECTs. A driver that does not hold a
    read snapshot — pysqlite runs SELECTs outside a transaction, and any
    autocommit read behaves the same — can read the project row before the
    worker thread commits the stage and the job row after it. The response
    then says `completed` while still carrying the state from before the job
    ran, and the client, which stops polling on `completed`, is left looking
    at a screen that never advanced. It is a narrow window, and a job that
    lands in it is exactly the one the user is watching.
    """
    job = (
        db.query(GenerationJob)
        .filter(GenerationJob.project_id == project.id, GenerationJob.job_type == job_type)
        .order_by(GenerationJob.created_at.desc())
        .first()
    )
    db.expire(project)
    return job


def _advance(db: Session, project: Project, *, when: tuple, to: ProjectState, note: str) -> None:
    """Move the project on only from the states this stage is responsible for.

    A re-run started from further down the workflow must not drag the project
    backwards through states the user has already approved past.
    """
    if project.state in when:
        approval_service.set_state(db, project, to, note=note)


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------
def start_analysis(db: Session, project: Project) -> GenerationJob:
    _advance(
        db, project,
        when=(ProjectState.DRAFT.value, ProjectState.ANALYSIS_READY.value),
        to=ProjectState.ANALYZING, note="analysis started",
    )
    return create_job(db, project=project, job_type=JobType.ANALYSIS.value, estimated_cost_usd=0.0)


@register_handler(JobType.ANALYSIS.value)
def _handle_analysis(db: Session, job: GenerationJob) -> Dict[str, Any]:
    project = _project(db, job)
    set_progress(db, job, 0.05, "reading the brief")

    # The label used to be set once, before any work, and never moved until
    # the stage was over. So a job spending minutes fetching assets displayed
    # "understanding the brief" throughout — the screen was not slow, it was
    # wrong about what it was doing, which is why "it never finishes" was the
    # only thing left to say about it.
    def _measuring(done: int, total: int, kind: str) -> None:
        share = done / total if total else 1.0
        set_progress(db, job, 0.05 + 0.45 * share, f"measuring your media ({done}/{total})")

    analysis = run_analysis(db, project, on_progress=_measuring)
    set_progress(db, job, 0.9, "writing the report")
    _advance(
        db, project, when=(ProjectState.ANALYZING.value,),
        to=ProjectState.ANALYSIS_READY, note="analysis ready",
    )
    db.commit()
    return {"analysis_id": analysis.id, "version": analysis.version, "state": project.state}


# --------------------------------------------------------------------------
# Concepts
# --------------------------------------------------------------------------
def start_concepts(db: Session, project: Project, *, regenerate: bool = False) -> GenerationJob:
    approval_service.require_approval(db, project, WorkflowStage.CONCEPTS)
    return create_job(
        db, project=project, job_type=JobType.CONCEPTS.value,
        payload={"regenerate": regenerate}, estimated_cost_usd=0.0,
    )


@register_handler(JobType.CONCEPTS.value)
def _handle_concepts(db: Session, job: GenerationJob) -> Dict[str, Any]:
    project = _project(db, job)
    set_progress(db, job, 0.2, "developing concepts")
    created = concept_service.generate_concepts(
        db, project, regenerate=bool((job.payload or {}).get("regenerate"))
    )
    _advance(
        db, project, when=(ProjectState.ANALYSIS_READY.value,),
        to=ProjectState.CONCEPT_REVIEW, note="concepts generated",
    )
    db.commit()
    return {"concept_count": len(created), "state": project.state}


# --------------------------------------------------------------------------
# Script — three variants, three model calls, the slowest stage of all
# --------------------------------------------------------------------------
def start_script(db: Session, project: Project, *, regenerate: bool = False) -> GenerationJob:
    approval_service.require_approval(db, project, WorkflowStage.SCRIPT)
    return create_job(
        db, project=project, job_type=JobType.SCRIPT.value,
        payload={"regenerate": regenerate}, estimated_cost_usd=0.0,
    )


@register_handler(JobType.SCRIPT.value)
def _handle_script(db: Session, job: GenerationJob) -> Dict[str, Any]:
    project = _project(db, job)
    set_progress(db, job, 0.2, "writing the script")
    created = script_service.generate_scripts(
        db, project, regenerate=bool((job.payload or {}).get("regenerate"))
    )
    _advance(
        db, project, when=(ProjectState.CONCEPT_APPROVED.value,),
        to=ProjectState.SCRIPT_REVIEW, note="script drafted",
    )
    db.commit()
    return {"variant_count": len(created), "state": project.state}


# --------------------------------------------------------------------------
# Storyboard
# --------------------------------------------------------------------------
def start_storyboard(db: Session, project: Project, *, regenerate: bool = False) -> GenerationJob:
    approval_service.require_approval(db, project, WorkflowStage.STORYBOARD)
    return create_job(
        db, project=project, job_type=JobType.STORYBOARD.value,
        payload={"regenerate": regenerate}, estimated_cost_usd=0.0,
    )


@register_handler(JobType.STORYBOARD.value)
def _handle_storyboard(db: Session, job: GenerationJob) -> Dict[str, Any]:
    project = _project(db, job)
    set_progress(db, job, 0.2, "building the storyboard")
    storyboard = storyboard_service.build_storyboard(
        db, project, regenerate=bool((job.payload or {}).get("regenerate"))
    )
    _advance(
        db, project,
        when=(ProjectState.SCRIPT_APPROVED.value, ProjectState.STORYBOARD_APPROVED.value),
        to=ProjectState.STORYBOARD_REVIEW, note="storyboard built",
    )
    db.commit()
    return {"storyboard_id": storyboard.id, "state": project.state}


def _project(db: Session, job: GenerationJob) -> Project:
    project = db.get(Project, job.project_id)
    if project is None:  # pragma: no cover - defensive
        raise ValueError(f"Project {job.project_id} is gone")
    return project
