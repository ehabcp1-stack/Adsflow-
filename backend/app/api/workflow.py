"""Workflow stages: analysis → concepts → script → voice → storyboard."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_project
from app.core.db import get_db
from app.core.enums import ApprovalEntity, JobType, ProjectState, WorkflowStage
from app.core.errors import NotFound
from app.core.security import get_current_user
from app.models import Concept, Project, ScriptVersion, Scene, User, VoiceProfile
from app.schemas import (
    ApproveRequest,
    LockRequest,
    RefineRequest,
    SceneUpdate,
    ScriptLinesUpdate,
    SelectRequest,
    VoicePreviewRequest,
    VoiceSelectRequest,
)
from app.services import approvals as approval_service
from app.services import concepts as concept_service
from app.services import scripts as script_service
from app.services import storyboards as storyboard_service
from app.services import voices as voice_service
from app.services import stage_jobs
from app.services.analysis import ANALYSIS_STEPS
from app.services.jobs import dispatch, job_payload
from app.services.dialect import list_presets
from app.services.director import notes_for_stage

router = APIRouter(prefix="/projects/{project_id}", tags=["workflow"])


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------
def _analysis_payload(analysis) -> Dict[str, Any]:
    return {
        "id": analysis.id,
        "version": analysis.version,
        "brief_interpretation": analysis.brief_interpretation,
        "asset_analysis": analysis.asset_analysis,
        "creative_strategy": analysis.creative_strategy,
        "production_recommendation": analysis.production_recommendation,
        "recommended_mode": analysis.recommended_mode,
        "recommended_duration_sec": analysis.recommended_duration_sec,
        "recommended_angle": analysis.recommended_angle,
        "recommended_voice_style": analysis.recommended_voice_style,
        "estimated_cost_usd": analysis.estimated_cost_usd,
        "readiness_score": analysis.readiness_score,
        "confidence_score": analysis.confidence_score,
        "director_notes": analysis.director_notes,
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
    }


@router.get("/analysis")
def get_analysis(project: Project = Depends(get_project), db: Session = Depends(get_db)) -> Dict[str, Any]:
    # The job is read first on purpose — see `stage_jobs.latest_job`.
    job = stage_jobs.latest_job(db, project, JobType.ANALYSIS.value)
    analysis = concept_service.latest_analysis(db, project)
    return {
        "steps": ANALYSIS_STEPS,
        "analysis": _analysis_payload(analysis) if analysis else None,
        "versions": [{"id": a.id, "version": a.version} for a in sorted(project.analyses, key=lambda a: -a.version)],
        # The UI polls this endpoint while the job runs; without it the only
        # signal of a failed analysis is an empty screen.
        "job": job_payload(job) if job else None,
        "state": project.state,
    }


@router.post("/analysis/run")
def run_project_analysis(project: Project = Depends(get_project), db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Queue the analysis and return immediately.

    This used to call `run_analysis` inline. Against a real LLM that is a
    ~90-second call chain, and the browser gave up at ~40 with
    "cannot reach the server" — taking the half-finished transaction with it,
    so the analysis was not merely unseen, it was lost. The client now polls
    `GET /analysis`.
    """
    job = stage_jobs.start_analysis(db, project)
    # Commit before dispatching: the worker reads the job through its own
    # session, and an uncommitted row does not exist as far as it is concerned.
    db.commit()
    dispatch(job.id)
    analysis = concept_service.latest_analysis(db, project)
    return {
        "steps": ANALYSIS_STEPS,
        "analysis": _analysis_payload(analysis) if analysis else None,
        "job": job_payload(job),
        "state": project.state,
    }


@router.post("/analysis/approve")
def approve_analysis(
    payload: Optional[ApproveRequest] = None,
    project: Project = Depends(get_project),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    payload = payload or ApproveRequest()
    analysis = concept_service.latest_analysis(db, project)
    if not analysis:
        raise NotFound("Run the analysis first.", "شغّل التحليل أول.")
    approval_service.approve(
        db, project=project, entity=ApprovalEntity.ANALYSIS, entity_id=analysis.id,
        version=analysis.version, user_id=user.id, notes=payload.notes,
    )
    approval_service.set_state(db, project, ProjectState.CONCEPT_REVIEW, note="analysis approved")
    db.commit()
    return {"ok": True, "state": project.state}


# --------------------------------------------------------------------------
# Concepts
# --------------------------------------------------------------------------
@router.get("/concepts")
def get_concepts(project: Project = Depends(get_project), db: Session = Depends(get_db)) -> Dict[str, Any]:
    job = stage_jobs.latest_job(db, project, JobType.CONCEPTS.value)
    items = sorted(project.concepts, key=lambda c: (c.is_alternative, -c.score_total))
    return {
        "items": [concept_service.concept_payload(c) for c in items if not c.is_alternative][:3],
        "alternatives": [concept_service.concept_payload(c) for c in items if c.is_alternative],
        "actions": concept_service.REFINE_ACTIONS,
        "selected_concept_id": project.selected_concept_id,
        "director_notes": notes_for_stage(db, project, WorkflowStage.CONCEPTS),
        "job": job_payload(job) if job else None,
        "state": project.state,
    }


@router.post("/concepts/generate")
def generate_concepts(
    project: Project = Depends(get_project), db: Session = Depends(get_db), regenerate: bool = False
) -> Dict[str, Any]:
    """Queue the concept work. See services/stage_jobs.py for why."""
    job = stage_jobs.start_concepts(db, project, regenerate=regenerate)
    db.commit()
    dispatch(job.id)
    return {**get_concepts(project=project, db=db), "job": job_payload(job)}


@router.post("/concepts/select")
def select_concept(
    payload: SelectRequest, project: Project = Depends(get_project), db: Session = Depends(get_db)
) -> Dict[str, Any]:
    concept = concept_service.select_concept(db, project, payload.id)
    db.commit()
    return concept_service.concept_payload(concept)


@router.post("/concepts/{concept_id}/refine")
def refine_concept(
    concept_id: str, payload: RefineRequest, project: Project = Depends(get_project), db: Session = Depends(get_db)
) -> Dict[str, Any]:
    concept = db.get(Concept, concept_id)
    if not concept or concept.project_id != project.id:
        raise NotFound("Concept not found.", "الفكرة غير موجودة.")
    concept_service.refine_concept(db, project, concept, payload.action)
    db.commit()
    return concept_service.concept_payload(concept)


@router.post("/concepts/approve")
def approve_concept(
    payload: Optional[ApproveRequest] = None,
    project: Project = Depends(get_project),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    payload = payload or ApproveRequest()
    concept_id = payload.entity_id or project.selected_concept_id
    if not concept_id:
        raise NotFound("Select a concept first.", "اختر فكرة أول.")
    concept = concept_service.select_concept(db, project, concept_id)
    approval_service.approve(
        db, project=project, entity=ApprovalEntity.CONCEPT, entity_id=concept.id,
        version=concept.version, user_id=user.id, notes=payload.notes,
    )
    approval_service.set_state(db, project, ProjectState.CONCEPT_APPROVED, note="concept approved")
    db.commit()
    return {"ok": True, "state": project.state, "concept_id": concept.id}


# --------------------------------------------------------------------------
# Script
# --------------------------------------------------------------------------
@router.get("/script")
def get_script(project: Project = Depends(get_project), db: Session = Depends(get_db)) -> Dict[str, Any]:
    job = stage_jobs.latest_job(db, project, JobType.SCRIPT.value)
    scripts = sorted(project.scripts, key=lambda s: (s.variant, -s.version))
    latest_by_variant: Dict[str, Any] = {}
    for script in scripts:
        latest_by_variant.setdefault(script.variant, script)
    return {
        "variants": [script_service.script_payload(s) for s in latest_by_variant.values()],
        "selected_script_id": project.selected_script_id,
        "actions": script_service.REFINE_ACTIONS,
        "dialect_presets": list_presets(),
        "job": job_payload(job) if job else None,
        "state": project.state,
    }


@router.post("/script/generate")
def generate_script(
    project: Project = Depends(get_project), db: Session = Depends(get_db), regenerate: bool = False
) -> Dict[str, Any]:
    """Queue the script work — three variants, three model calls, the longest
    stage in the product. See services/stage_jobs.py."""
    job = stage_jobs.start_script(db, project, regenerate=regenerate)
    db.commit()
    dispatch(job.id)
    return {**get_script(project=project, db=db), "job": job_payload(job)}


@router.post("/script/select")
def select_script(
    payload: SelectRequest, project: Project = Depends(get_project), db: Session = Depends(get_db)
) -> Dict[str, Any]:
    script = script_service.select_script(db, project, payload.id)
    db.commit()
    return script_service.script_payload(script)


@router.post("/script/{script_id}/refine")
def refine_script(
    script_id: str, payload: RefineRequest, project: Project = Depends(get_project), db: Session = Depends(get_db)
) -> Dict[str, Any]:
    script = db.get(ScriptVersion, script_id)
    if not script or script.project_id != project.id:
        raise NotFound("Script not found.", "النص غير موجود.")
    new_version = script_service.refine_script(db, project, script, payload.action, new_cta=payload.new_cta)
    approval_service.invalidate_downstream(
        db, project=project, changed_entity=ApprovalEntity.SCRIPT, reason="script refined"
    )
    db.commit()
    return script_service.script_payload(new_version)


@router.patch("/script/{script_id}")
def edit_script(
    script_id: str, payload: ScriptLinesUpdate, project: Project = Depends(get_project), db: Session = Depends(get_db)
) -> Dict[str, Any]:
    script = db.get(ScriptVersion, script_id)
    if not script or script.project_id != project.id:
        raise NotFound("Script not found.", "النص غير موجود.")
    new_version = script_service.update_script_text(db, project, script, payload.lines)
    approval_service.invalidate_downstream(
        db, project=project, changed_entity=ApprovalEntity.SCRIPT, reason="script edited"
    )
    db.commit()
    return script_service.script_payload(new_version)


@router.get("/script/hooks")
def script_hooks(
    project: Project = Depends(get_project), db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Testable openings for the selected script. Deterministic, zero cost."""
    from app.services import hooks as hook_service

    script = db.get(ScriptVersion, project.selected_script_id) if project.selected_script_id else None
    if not script:
        raise NotFound("Select a script first.", "اختر النص أول.")
    variants = hook_service.generate_variants(
        script_service.script_payload(script), project_name=project.name, limit=5
    )
    return {
        "script_id": script.id,
        "window_sec": hook_service.HOOK_WINDOW_SEC,
        "variants": [variant.as_dict() for variant in variants],
    }


@router.post("/script/hooks/{variant_key}/apply")
def apply_script_hook(
    variant_key: str, project: Project = Depends(get_project), db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Adopt one opening as a new script version.

    A new version rather than an edit in place: the point of hook testing is to
    keep both and compare them, so the previous opening stays in history.
    """
    from app.services import hooks as hook_service

    script = db.get(ScriptVersion, project.selected_script_id) if project.selected_script_id else None
    if not script:
        raise NotFound("Select a script first.", "اختر النص أول.")
    payload = script_service.script_payload(script)
    variants = hook_service.generate_variants(payload, project_name=project.name, limit=5)
    chosen = next((v for v in variants if v.key == variant_key), None)
    if chosen is None:
        raise NotFound("Unknown hook variant.", "الخطّاف غير موجود.")

    lines = hook_service.apply_to_script_lines(script.lines or [], chosen)
    new_version = script_service.update_script_text(db, project, script, lines)
    new_version.hook_variant = chosen.key
    approval_service.invalidate_downstream(
        db, project=project, changed_entity=ApprovalEntity.SCRIPT,
        reason=f"hook variant '{chosen.key}' applied",
    )
    db.commit()
    return {**script_service.script_payload(new_version), "hook_variant": chosen.key}


@router.post("/script/approve")
def approve_script(
    payload: Optional[ApproveRequest] = None,
    project: Project = Depends(get_project),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    payload = payload or ApproveRequest()
    script_id = payload.entity_id or project.selected_script_id
    if not script_id:
        raise NotFound("Select a script first.", "اختر النص أول.")
    script = script_service.select_script(db, project, script_id)
    approval_service.approve(
        db, project=project, entity=ApprovalEntity.SCRIPT, entity_id=script.id,
        version=script.version, user_id=user.id, notes=payload.notes,
    )
    approval_service.set_state(db, project, ProjectState.SCRIPT_APPROVED, note="script approved")
    db.commit()
    return {"ok": True, "state": project.state, "script_id": script.id}


# --------------------------------------------------------------------------
# Voice
# --------------------------------------------------------------------------
@router.get("/voice")
def get_voice(project: Project = Depends(get_project), db: Session = Depends(get_db)) -> Dict[str, Any]:
    profiles = voice_service.ensure_demo_voices(db, project.organization_id)
    db.commit()
    script = db.get(ScriptVersion, project.selected_script_id) if project.selected_script_id else None
    return {
        "profiles": [voice_service.voice_payload(p) for p in profiles],
        "selected_voice_profile_id": project.selected_voice_profile_id,
        "voice_locked": project.voice_locked,
        "voice_over_enabled": project.voice_over_enabled,
        "sample_text": script_service.spoken_hook(script),
        "timing": voice_service.voice_timing(db, project, script) if script else [],
        "pronunciation": voice_service.pronunciation_for_project(db, project),
        "director_notes": notes_for_stage(db, project, WorkflowStage.VOICE),
        "state": project.state,
    }


@router.post("/voice/preview")
def preview_voice(
    payload: VoicePreviewRequest, project: Project = Depends(get_project), db: Session = Depends(get_db)
) -> Dict[str, Any]:
    profile = db.get(VoiceProfile, payload.voice_profile_id)
    if not profile:
        raise NotFound("Voice profile not found.", "الصوت غير موجود.")
    script = db.get(ScriptVersion, project.selected_script_id) if project.selected_script_id else None
    text = payload.text or script_service.spoken_hook(script)
    result = voice_service.preview_voice(
        db, profile=profile, text=text, speed=payload.speed, energy=payload.energy, emotion=payload.emotion
    )
    db.commit()
    return result


@router.post("/voice/select")
def select_voice(
    payload: VoiceSelectRequest, project: Project = Depends(get_project), db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    profile = voice_service.select_voice(db, project, payload.voice_profile_id, lock=payload.lock)
    if payload.speed is not None:
        profile.speed = payload.speed
    if payload.energy is not None:
        profile.energy = payload.energy
    if payload.emotion is not None:
        profile.emotion = payload.emotion
    if payload.lock:
        approval_service.approve(
            db, project=project, entity=ApprovalEntity.VOICE, entity_id=profile.id, user_id=user.id, notes="voice locked"
        )
    db.commit()
    return {"ok": True, "profile": voice_service.voice_payload(profile), "voice_locked": project.voice_locked}


# --------------------------------------------------------------------------
# Storyboard
# --------------------------------------------------------------------------
@router.get("/storyboard")
def get_storyboard(project: Project = Depends(get_project), db: Session = Depends(get_db)) -> Dict[str, Any]:
    job = stage_jobs.latest_job(db, project, JobType.STORYBOARD.value)
    storyboard = storyboard_service.active_storyboard(db, project)
    return {
        "storyboard": storyboard_service.storyboard_payload(db, storyboard) if storyboard else None,
        "job": job_payload(job) if job else None,
        "state": project.state,
    }


@router.post("/storyboard/generate")
def generate_storyboard(
    project: Project = Depends(get_project), db: Session = Depends(get_db), regenerate: bool = False
) -> Dict[str, Any]:
    """Queue the storyboard work. See services/stage_jobs.py."""
    job = stage_jobs.start_storyboard(db, project, regenerate=regenerate)
    db.commit()
    dispatch(job.id)
    return {**get_storyboard(project=project, db=db), "job": job_payload(job)}


@router.patch("/scenes/{scene_id}")
def update_scene(
    scene_id: str, payload: SceneUpdate, project: Project = Depends(get_project), db: Session = Depends(get_db)
) -> Dict[str, Any]:
    scene = db.get(Scene, scene_id)
    if not scene:
        raise NotFound("Scene not found.", "المشهد غير موجود.")
    storyboard_service.update_scene(db, scene, payload.changes)
    approval_service.invalidate_downstream(
        db, project=project, changed_entity=ApprovalEntity.STORYBOARD, reason="scene changed"
    )
    db.commit()
    return storyboard_service.scene_payload(scene)


@router.post("/scenes/{scene_id}/cheaper")
def scene_cheaper(scene_id: str, project: Project = Depends(get_project), db: Session = Depends(get_db)) -> Dict[str, Any]:
    scene = db.get(Scene, scene_id)
    if not scene:
        raise NotFound("Scene not found.", "المشهد غير موجود.")
    storyboard_service.make_cheaper(db, scene)
    _refresh_plan(db, project)
    db.commit()
    return storyboard_service.scene_payload(scene)


@router.post("/scenes/{scene_id}/premium")
def scene_premium(scene_id: str, project: Project = Depends(get_project), db: Session = Depends(get_db)) -> Dict[str, Any]:
    scene = db.get(Scene, scene_id)
    if not scene:
        raise NotFound("Scene not found.", "المشهد غير موجود.")
    storyboard_service.make_premium(db, scene)
    _refresh_plan(db, project)
    db.commit()
    return storyboard_service.scene_payload(scene)


@router.post("/scenes/{scene_id}/lock")
def scene_lock(
    scene_id: str, payload: LockRequest, project: Project = Depends(get_project), db: Session = Depends(get_db)
) -> Dict[str, Any]:
    scene = db.get(Scene, scene_id)
    if not scene:
        raise NotFound("Scene not found.", "المشهد غير موجود.")
    storyboard_service.set_lock(db, scene, payload.locked)
    db.commit()
    return storyboard_service.scene_payload(scene)


@router.post("/scenes/{scene_id}/keyframe/approve")
def scene_keyframe_approve(
    scene_id: str, project: Project = Depends(get_project), db: Session = Depends(get_db)
) -> Dict[str, Any]:
    from app.services.production import approve_keyframe

    scene = db.get(Scene, scene_id)
    if not scene:
        raise NotFound("Scene not found.", "المشهد غير موجود.")
    approve_keyframe(db, scene, True)
    db.commit()
    return storyboard_service.scene_payload(scene)


def _refresh_plan(db: Session, project: Project) -> None:
    storyboard = storyboard_service.active_storyboard(db, project)
    if storyboard:
        storyboard.estimated_cost_usd = round(sum(s.estimated_cost_usd for s in storyboard.scenes), 4)
        storyboard.production_plan = storyboard_service.build_production_plan(db, project, storyboard)
        storyboard.continuity_report = storyboard_service.check_continuity(db, storyboard)
        project.estimated_cost_usd = storyboard.production_plan["estimated_total_usd"]


@router.post("/storyboard/approve")
def approve_storyboard(
    payload: Optional[ApproveRequest] = None,
    project: Project = Depends(get_project),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    payload = payload or ApproveRequest()
    storyboard = storyboard_service.active_storyboard(db, project)
    if not storyboard:
        raise NotFound("Build the storyboard first.", "سوّي الستوري بورد أول.")
    _refresh_plan(db, project)
    approval_service.approve(
        db, project=project, entity=ApprovalEntity.STORYBOARD, entity_id=storyboard.id,
        version=storyboard.version, user_id=user.id, notes=payload.notes,
    )
    approval_service.set_state(db, project, ProjectState.STORYBOARD_APPROVED, note="storyboard approved")
    db.commit()
    return {"ok": True, "state": project.state, "storyboard_id": storyboard.id}
