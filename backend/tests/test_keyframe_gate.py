"""Hero-frame-first: no AI video is bought before a human approves the still.

The economics this protects: a rejected still costs cents, a rejected 8-second
video take costs roughly a dollar. Generating video blind and hoping is how a
$50 monthly budget disappears in an afternoon.
"""
from __future__ import annotations

import pytest

from app.core.config import settings
from app.core.enums import JobType, ProductionMethod, SceneStatus
from app.models import GenerationJob, Scene, Storyboard
from app.services import production as production_service
from app.services.jobs import create_job, execute_job


@pytest.fixture
def ai_video_scene(db, make_project):
    """A project with one storyboard holding a single AI-video scene."""
    project = make_project(name="لقطة بطل")
    storyboard = Storyboard(project_id=project.id, version=1, total_duration_sec=8.0, is_active=True)
    db.add(storyboard)
    db.flush()
    scene = Scene(
        storyboard_id=storyboard.id,
        scene_number=1,
        start_time=0.0,
        end_time=6.0,
        production_method=ProductionMethod.AI_VIDEO.value,
        recommended_provider="mock",
        recommended_model="mock-video-v1",
        estimated_cost_usd=0.0,
        is_hero=True,
        compiled_prompt={"subject": "واجهة المشروع", "references": []},
    )
    db.add(scene)
    db.commit()
    return project, scene


def _run_scene_job(db, project, scene):
    job = create_job(
        db,
        project=project,
        job_type=JobType.VIDEO_GENERATION.value,
        scene_id=scene.id,
        payload={"scene_number": scene.scene_number},
    )
    db.commit()
    # Run it on this thread: the inline dispatcher is a thread pool, and a job
    # still running after the session fixture drops the schema is a flake, not
    # a finding.
    execute_job(db, job.id)
    db.expire_all()
    return (db.get(GenerationJob, job.id).result) or {}


def test_an_ai_video_scene_stops_at_the_keyframe(db, ai_video_scene, monkeypatch):
    monkeypatch.setattr(settings, "REQUIRE_KEYFRAME_APPROVAL", True)
    project, scene = ai_video_scene

    result = _run_scene_job(db, project, scene)

    db.expire_all()
    scene = db.get(Scene, scene.id)
    assert result["awaiting_keyframe_approval"] is True
    assert result["stage"] == "keyframe"
    assert scene.keyframe_url, "the still must actually exist for a human to judge"
    assert scene.keyframe_approved is False
    assert scene.status == SceneStatus.REVIEWING.value
    # The expensive step must NOT have happened.
    assert scene.output_url is None


def test_approving_the_keyframe_is_what_releases_the_video_spend(db, ai_video_scene, monkeypatch):
    monkeypatch.setattr(settings, "REQUIRE_KEYFRAME_APPROVAL", True)
    project, scene = ai_video_scene
    _run_scene_job(db, project, scene)
    db.expire_all()
    scene = db.get(Scene, scene.id)

    before = db.query(GenerationJob).filter(
        GenerationJob.project_id == project.id,
        GenerationJob.job_type == JobType.VIDEO_GENERATION.value,
    ).count()

    production_service.approve_keyframe(db, scene, True)
    db.commit()
    db.expire_all()

    after = db.query(GenerationJob).filter(
        GenerationJob.project_id == project.id,
        GenerationJob.job_type == JobType.VIDEO_GENERATION.value,
    ).count()
    assert after == before + 1, "approval must queue exactly one video job"
    assert db.get(Scene, scene.id).keyframe_approved is True


def test_approving_twice_does_not_buy_the_video_twice(db, ai_video_scene, monkeypatch):
    monkeypatch.setattr(settings, "REQUIRE_KEYFRAME_APPROVAL", True)
    project, scene = ai_video_scene
    _run_scene_job(db, project, scene)
    db.expire_all()
    scene = db.get(Scene, scene.id)

    production_service.approve_keyframe(db, scene, True)
    db.commit()
    production_service.wait_for_jobs(db, project, timeout_sec=20.0)
    db.expire_all()
    scene = db.get(Scene, scene.id)
    assert scene.output_url, "the released video job should have produced output"

    jobs_after_first = db.query(GenerationJob).filter(
        GenerationJob.project_id == project.id,
        GenerationJob.job_type == JobType.VIDEO_GENERATION.value,
    ).count()

    production_service.approve_keyframe(db, scene, True)
    db.commit()
    jobs_after_second = db.query(GenerationJob).filter(
        GenerationJob.project_id == project.id,
        GenerationJob.job_type == JobType.VIDEO_GENERATION.value,
    ).count()
    assert jobs_after_second == jobs_after_first


def test_rejecting_the_keyframe_spends_nothing_more(db, ai_video_scene, monkeypatch):
    monkeypatch.setattr(settings, "REQUIRE_KEYFRAME_APPROVAL", True)
    project, scene = ai_video_scene
    _run_scene_job(db, project, scene)
    db.expire_all()
    scene = db.get(Scene, scene.id)

    before = db.query(GenerationJob).filter(
        GenerationJob.project_id == project.id,
        GenerationJob.job_type == JobType.VIDEO_GENERATION.value,
    ).count()
    production_service.approve_keyframe(db, scene, False)
    db.commit()
    after = db.query(GenerationJob).filter(
        GenerationJob.project_id == project.id,
        GenerationJob.job_type == JobType.VIDEO_GENERATION.value,
    ).count()
    assert after == before
    assert db.get(Scene, scene.id).output_url is None


def test_the_gate_can_be_switched_off_for_unattended_runs(db, ai_video_scene, monkeypatch):
    monkeypatch.setattr(settings, "REQUIRE_KEYFRAME_APPROVAL", False)
    project, scene = ai_video_scene

    result = _run_scene_job(db, project, scene)

    assert "awaiting_keyframe_approval" not in result
    db.expire_all()
    assert db.get(Scene, scene.id).output_url


def test_a_local_scene_is_never_gated(db, make_project, monkeypatch):
    """Photo motion costs nothing, so a gate there is pure friction."""
    monkeypatch.setattr(settings, "REQUIRE_KEYFRAME_APPROVAL", True)
    scene = Scene(
        storyboard_id="x", scene_number=1, start_time=0.0, end_time=3.0,
        production_method=ProductionMethod.PHOTO_MOTION.value,
    )
    assert production_service._needs_keyframe_first(scene) is False


def test_the_keyframe_uses_the_cheapest_image_tier():
    """A draft frame is thrown away often; it must not be billed as a hero."""
    from app.providers import catalog

    provider_id, model_id = production_service._keyframe_model()
    spec = catalog.spec(provider_id, model_id)
    assert spec is not None
    assert spec.quality_tier == "economy"
