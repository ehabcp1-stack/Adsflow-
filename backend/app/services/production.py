"""Production Orchestrator + Generation Manager + Retry System.

Independent jobs, critical scenes first, cost-checked at every paid step.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import (
    ApprovalEntity,
    CostStatus,
    JobStatus,
    JobType,
    ProductionMethod,
    ProjectState,
    SceneStatus,
    WorkflowStage,
)
from app.core.errors import NotFound
from app.models import GenerationJob, Project, ProviderRun, Scene, ScriptVersion, Storyboard, VoiceProfile
from app.providers import model_router
from app.providers.quality_judge import judge_scene, plan_retry
from app.providers.registry import get_image, get_music, get_video, get_voice
from app.services import approvals as approval_service
from app.services import costs as cost_service
from app.services.jobs import create_job, dispatch, register_handler, set_progress
from app.services.scene_render import LOCAL_METHODS, render_local_scene
from app.services.storyboards import active_storyboard


def _scene_job_type(scene: Scene) -> str:
    if scene.production_method == ProductionMethod.AI_VIDEO.value:
        return JobType.VIDEO_GENERATION.value
    if scene.production_method == ProductionMethod.AI_IMAGE.value:
        return JobType.IMAGE_GENERATION.value
    if scene.production_method == ProductionMethod.ORIGINAL_VIDEO.value:
        return JobType.VIDEO_TRANSFORM.value
    if scene.production_method == ProductionMethod.PHOTO_MOTION.value:
        return JobType.PHOTO_MOTION.value
    return JobType.PHOTO_MOTION.value


def start_production(db: Session, project: Project, *, user_id: Optional[str] = None) -> List[GenerationJob]:
    """Create and dispatch all jobs for the approved production plan."""
    approval_service.require_approval(db, project, WorkflowStage.PRODUCTION)
    storyboard = active_storyboard(db, project)
    if not storyboard:
        raise NotFound("No storyboard to produce.", "ما أكو ستوري بورد للإنتاج.")

    plan = storyboard.production_plan or {}
    paid_total = round(
        plan.get("video_cost_usd", 0) + plan.get("image_cost_usd", 0) + plan.get("voice_cost_usd", 0), 4
    )
    cost_service.check_can_spend(db, project, paid_total, operation="production run")

    if project.state != ProjectState.GENERATING.value:
        approval_service.set_state(db, project, ProjectState.GENERATING, note="production started")

    jobs: List[GenerationJob] = []
    scenes = sorted(storyboard.scenes, key=lambda s: (-s.priority, s.scene_number))

    # Voice first — scene timing depends on it.
    script = db.get(ScriptVersion, storyboard.script_version_id) if storyboard.script_version_id else None
    if project.voice_over_enabled and script:
        jobs.append(
            create_job(
                db,
                project=project,
                job_type=JobType.VOICE_GENERATION.value,
                payload={"script_id": script.id},
                estimated_cost_usd=plan.get("voice_cost_usd", 0.0),
            )
        )
    jobs.append(
        create_job(
            db,
            project=project,
            job_type=JobType.MUSIC_GENERATION.value,
            payload={"mood": project.tone, "duration_sec": storyboard.total_duration_sec},
            estimated_cost_usd=plan.get("music_cost_usd", 0.0),
        )
    )

    for scene in scenes:
        if scene.locked and scene.output_url:
            continue
        jobs.append(
            create_job(
                db,
                project=project,
                job_type=_scene_job_type(scene),
                scene_id=scene.id,
                payload={"scene_number": scene.scene_number},
                estimated_cost_usd=scene.estimated_cost_usd,
            )
        )
        scene.status = SceneStatus.GENERATING.value

    for job in jobs:
        if job.estimated_cost_usd > 0:
            cost_service.record_cost(
                db,
                project=project,
                provider="pending",
                model="pending",
                operation=job.job_type,
                estimated=job.estimated_cost_usd,
                status=CostStatus.RESERVED.value,
                scene_id=job.scene_id,
                job_id=job.id,
                note="reserved before generation",
            )
    db.commit()

    for job in jobs:
        dispatch(job.id)
    return jobs


# --------------------------------------------------------------------------
# Job handlers
# --------------------------------------------------------------------------
def _finish_cost(db: Session, job: GenerationJob, provider: str, model: str, actual: float) -> None:
    project = db.get(Project, job.project_id)
    job.actual_cost_usd = actual
    cost_service.record_cost(
        db,
        project=project,
        provider=provider,
        model=model,
        operation=job.job_type,
        estimated=job.estimated_cost_usd,
        actual=actual,
        status=CostStatus.ACTUAL.value,
        scene_id=job.scene_id,
        job_id=job.id,
        is_mock=provider in ("mock", "local"),
        note="completed",
    )
    if job.scene_id:
        scene = db.get(Scene, job.scene_id)
        if scene:
            scene.actual_cost_usd = round(scene.actual_cost_usd + actual, 4)


def _record_run(
    db: Session, job: GenerationJob, *, provider: str, model: str, operation: str, result: Any, quality: Optional[float]
) -> ProviderRun:
    run = ProviderRun(
        job_id=job.id,
        provider=provider,
        model=model,
        operation=operation,
        is_mock=getattr(result, "is_mock", True),
        request_prompt=(job.payload or {}).get("prompt", {}),
        response_meta=getattr(result, "data", {}) or {},
        latency_ms=getattr(result, "latency_ms", 0),
        success=getattr(result, "ok", True),
        quality_score=quality,
        cost_usd=getattr(result, "cost_usd", 0.0),
    )
    db.add(run)
    db.flush()
    return run


def _produce_scene(db: Session, job: GenerationJob) -> Dict[str, Any]:
    scene = db.get(Scene, job.scene_id)
    project = db.get(Project, job.project_id)
    if not scene or not project:
        raise ValueError("Scene or project missing")

    attempt = job.attempt
    prompt = dict(scene.compiled_prompt or {})
    prompt["storage_key"] = f"projects/{project.id}/scenes/{scene.id}-a{attempt}.svg"
    duration = max(scene.end_time - scene.start_time, 1.5)

    set_progress(db, job, 0.15, "compiling prompt")

    provider_name = scene.recommended_provider
    model = scene.recommended_model
    cost = 0.0
    local_media: Dict[str, Any] = {}

    if scene.production_method in LOCAL_METHODS:
        # No provider, no spend: the customer's own material is rendered here.
        set_progress(db, job, 0.45, "rendering locally from your media")
        media = render_local_scene(db, project, scene)
        result_url = media["url"]
        if media.get("thumbnail_url"):
            scene.thumbnail_url = media["thumbnail_url"]
        quality = judge_scene(
            scene={"id": scene.id, "production_method": scene.production_method},
            result_meta={"real_media": media.get("real_media", False),
                         "renderer": media.get("renderer")},
            attempt=attempt,
        )
        provider_name, model = "local", media.get("renderer", "ffmpeg-pipeline")
        local_media = media
    else:
        if scene.production_method == ProductionMethod.AI_VIDEO.value:
            set_progress(db, job, 0.35, "generating cinematic video")
            provider = get_video(scene.recommended_provider)
            result = provider.generate_video(
                prompt=prompt, model=model, keyframe_url=scene.keyframe_url, duration_sec=duration
            )
        else:
            set_progress(db, job, 0.35, "generating image")
            provider = get_image(scene.recommended_provider)
            result = provider.generate_image(prompt=prompt, model=model, reference_urls=prompt.get("references"))
        if not result.ok:
            raise RuntimeError(result.error or "Provider failed")
        provider_name = result.provider
        model = result.model
        cost = result.cost_usd
        result_url = result.url
        quality = judge_scene(
            scene={"id": scene.id, "production_method": scene.production_method},
            result_meta={"quality_hint": result.quality_hint},
            attempt=attempt,
        )
        _record_run(db, job, provider=provider_name, model=model, operation=job.job_type, result=result, quality=quality.score)

    set_progress(db, job, 0.8, "quality check")
    scene.generation_attempts = attempt
    scene.quality_score = quality.score
    scene.quality_breakdown = quality.breakdown
    scene.output_url = result_url
    scene.thumbnail_url = scene.thumbnail_url or result_url

    if quality.passed:
        scene.status = SceneStatus.REVIEWING.value
    else:
        snapshot = cost_service.budget_snapshot(db, project)
        retry = plan_retry(
            attempt=attempt,
            max_attempts=job.max_attempts,
            budget_ok=snapshot["remaining_budget_usd"] > job.estimated_cost_usd,
        )
        if retry.should_retry:
            job.attempt = retry.next_attempt
            job.status = JobStatus.RETRYING.value
            job.progress_label = retry.strategy_ar
            if retry.switch_provider:
                decision = model_router.route(
                    scene={
                        "production_method": scene.production_method,
                        "start_time": scene.start_time,
                        "end_time": scene.end_time,
                        "is_hero": scene.is_hero,
                        "is_hook": scene.is_hook,
                    },
                    quality_level=project.quality_level,
                    remaining_budget_usd=snapshot["remaining_budget_usd"],
                    provider_performance={f"{scene.recommended_provider}:{scene.recommended_model}": -1.0},
                )
                scene.recommended_provider, scene.recommended_model = decision.provider, decision.model
            db.commit()
            return _produce_scene(db, job)
        scene.status = SceneStatus.REVIEWING.value

    _finish_cost(db, job, provider_name, model, cost)
    db.commit()
    return {
        "scene_id": scene.id,
        "url": scene.output_url,
        "quality_score": quality.score,
        "passed": quality.passed,
        "attempts": scene.generation_attempts,
        "provider": provider_name,
        "model": model,
        "renderer": local_media.get("renderer"),
        "real_media": local_media.get("real_media", provider_name not in ("local",)),
        "note": local_media.get("note"),
    }


@register_handler(JobType.IMAGE_GENERATION.value)
def _handle_image(db: Session, job: GenerationJob) -> Dict[str, Any]:
    return _produce_scene(db, job)


@register_handler(JobType.VIDEO_GENERATION.value)
def _handle_video(db: Session, job: GenerationJob) -> Dict[str, Any]:
    return _produce_scene(db, job)


@register_handler(JobType.PHOTO_MOTION.value)
def _handle_photo_motion(db: Session, job: GenerationJob) -> Dict[str, Any]:
    return _produce_scene(db, job)


@register_handler(JobType.VIDEO_TRANSFORM.value)
def _handle_video_transform(db: Session, job: GenerationJob) -> Dict[str, Any]:
    return _produce_scene(db, job)


@register_handler(JobType.VOICE_GENERATION.value)
def _handle_voice(db: Session, job: GenerationJob) -> Dict[str, Any]:
    project = db.get(Project, job.project_id)
    script = db.get(ScriptVersion, (job.payload or {}).get("script_id"))
    if not script:
        raise ValueError("Script missing for voice generation")
    profile = db.get(VoiceProfile, project.selected_voice_profile_id) if project.selected_voice_profile_id else None
    provider = get_voice(profile.provider if profile else None)
    set_progress(db, job, 0.4, "synthesizing Iraqi voice-over")
    result = provider.synthesize(
        text=script.voice_over_text,
        voice_id=profile.provider_voice_id if profile else "mock-iq-male-pro",
        speed=profile.speed if profile else 1.0,
        energy=profile.energy if profile else 0.6,
        emotion=profile.emotion if profile else 0.5,
    )
    if not result.ok:
        raise RuntimeError(result.error or "Voice provider failed")
    _record_run(db, job, provider=result.provider, model=result.model, operation="voice", result=result, quality=None)
    _finish_cost(db, job, result.provider, result.model, result.cost_usd)
    db.commit()
    return {"url": result.url, "duration_sec": result.data.get("duration_sec"), "provider": result.provider}


@register_handler(JobType.MUSIC_GENERATION.value)
def _handle_music(db: Session, job: GenerationJob) -> Dict[str, Any]:
    payload = job.payload or {}
    provider = get_music()
    set_progress(db, job, 0.5, "scoring music bed")
    result = provider.generate_music(
        brief={"mood": payload.get("mood", "cinematic")}, duration_sec=payload.get("duration_sec", 30.0)
    )
    _record_run(db, job, provider=result.provider, model=result.model, operation="music", result=result, quality=None)
    _finish_cost(db, job, result.provider, result.model, result.cost_usd)
    db.commit()
    return {"url": result.url, "bpm": result.data.get("bpm")}


# --------------------------------------------------------------------------
# Status & scene review
# --------------------------------------------------------------------------
def production_status(db: Session, project: Project) -> Dict[str, Any]:
    jobs = sorted(project.jobs, key=lambda j: j.created_at or 0)
    total = len(jobs) or 1
    done = sum(1 for j in jobs if j.status == JobStatus.COMPLETED.value)
    failed = [j for j in jobs if j.status == JobStatus.FAILED.value]
    storyboard = active_storyboard(db, project)
    scenes = sorted(storyboard.scenes, key=lambda s: s.scene_number) if storyboard else []
    return {
        "state": project.state,
        "jobs_total": len(jobs),
        "jobs_completed": done,
        "jobs_failed": len(failed),
        "progress": round(done / total, 3),
        "all_done": done == len(jobs) and len(jobs) > 0,
        "jobs": [
            {
                "id": j.id,
                "type": j.job_type,
                "status": j.status,
                "progress": j.progress,
                "label": j.progress_label,
                "scene_id": j.scene_id,
                "attempt": j.attempt,
                "error": j.error_message,
                "actual_cost_usd": j.actual_cost_usd,
            }
            for j in jobs
        ],
        "scenes": [
            {
                "id": s.id,
                "scene_number": s.scene_number,
                "status": s.status,
                "quality_score": s.quality_score,
                "output_url": s.output_url,
                "thumbnail_url": s.thumbnail_url,
                "locked": s.locked,
                "production_method": s.production_method,
                "actual_cost_usd": s.actual_cost_usd,
                "attempts": s.generation_attempts,
            }
            for s in scenes
        ],
    }


def approve_scene(db: Session, scene: Scene, *, lock: bool = False) -> Scene:
    scene.status = SceneStatus.LOCKED.value if lock else SceneStatus.APPROVED.value
    scene.locked = lock or scene.locked
    db.flush()
    return scene


def regenerate_scene(db: Session, project: Project, scene: Scene) -> GenerationJob:
    from app.services.storyboards import _assert_unlocked

    _assert_unlocked(scene)
    cost_service.check_can_spend(db, project, scene.estimated_cost_usd, operation="scene regeneration")
    scene.status = SceneStatus.GENERATING.value
    job = create_job(
        db,
        project=project,
        job_type=_scene_job_type(scene),
        scene_id=scene.id,
        payload={"scene_number": scene.scene_number, "regeneration": True},
        estimated_cost_usd=scene.estimated_cost_usd,
    )
    db.commit()
    dispatch(job.id)
    return job


def approve_keyframe(db: Session, scene: Scene, approved: bool = True) -> Scene:
    """Keyframe approval gate before expensive AI-video generation."""
    scene.keyframe_approved = approved
    db.flush()
    return scene


def wait_for_jobs(db: Session, project: Project, timeout_sec: float = 30.0) -> bool:
    """Used by tests and the seeder; the UI polls instead."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        db.expire_all()
        jobs = db.query(GenerationJob).filter(GenerationJob.project_id == project.id).all()
        if jobs and all(j.status in (JobStatus.COMPLETED.value, JobStatus.FAILED.value) for j in jobs):
            return True
        time.sleep(0.2)
    return False


def finish_production(db: Session, project: Project) -> Project:
    storyboard = active_storyboard(db, project)
    if storyboard:
        for scene in storyboard.scenes:
            if scene.status == SceneStatus.REVIEWING.value:
                scene.status = SceneStatus.APPROVED.value
    if project.state == ProjectState.GENERATING.value:
        approval_service.set_state(db, project, ProjectState.EDITING, note="generation complete")
    db.flush()
    return project
