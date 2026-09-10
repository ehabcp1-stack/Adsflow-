"""Versioning, locked scenes, dialect engine and QC scoring."""
from __future__ import annotations

import pytest

from app.core.enums import ApprovalEntity, ProductionMethod, ProjectState
from app.core.errors import SceneLocked
from app.services import approvals as approval_service
from app.services import concepts as concept_service
from app.services import scripts as script_service
from app.services import storyboards as storyboard_service
from app.services import voices as voice_service
from app.services.analysis import run_analysis
from app.services.dialect import (
    check_forbidden,
    estimate_speech_seconds,
    list_presets,
    spell_number_iraqi,
    spell_phone,
    to_on_screen,
)


@pytest.fixture
def ready_project(db, make_project):
    """A project analysed, with a selected concept and script."""
    project = make_project()
    run_analysis(db, project)
    approval_service.approve(db, project=project, entity=ApprovalEntity.ANALYSIS)
    created = concept_service.generate_concepts(db, project)
    concept_service.select_concept(db, project, created[0].id)
    approval_service.approve(db, project=project, entity=ApprovalEntity.CONCEPT)
    script_service.generate_scripts(db, project)
    approval_service.approve(db, project=project, entity=ApprovalEntity.SCRIPT)
    db.commit()
    return project


# --------------------------------------------------------------------------
# Versioning
# --------------------------------------------------------------------------
def test_analysis_versions_increment_and_history_is_kept(db, make_project):
    project = make_project()
    first = run_analysis(db, project)
    second = run_analysis(db, project)
    db.commit()
    assert first.version == 1 and second.version == 2
    assert len(project.analyses) == 2


def test_script_refinement_creates_a_new_version_and_keeps_the_concept(db, ready_project):
    original = next(s for s in ready_project.scripts if s.variant == "primary")
    concept_id = original.concept_id
    refined = script_service.refine_script(db, ready_project, original, "more_iraqi")
    db.commit()
    assert refined.id != original.id
    assert refined.version == original.version + 1
    assert refined.concept_id == concept_id  # concept preserved through refinement
    assert ready_project.selected_script_id == refined.id
    assert db.get(type(original), original.id) is not None  # approved history is not overwritten


def test_three_script_variants_are_produced(db, ready_project):
    variants = {s.variant for s in ready_project.scripts}
    assert {"primary", "more_sales", "more_emotional"} <= variants


def test_storyboard_regeneration_bumps_version(db, ready_project):
    first = storyboard_service.build_storyboard(db, ready_project)
    second = storyboard_service.build_storyboard(db, ready_project, regenerate=True)
    db.commit()
    assert second.version == first.version + 1
    assert second.is_active and not first.is_active


# --------------------------------------------------------------------------
# Locked scenes
# --------------------------------------------------------------------------
def test_locked_scene_cannot_be_changed_or_cheapened(db, ready_project):
    storyboard = storyboard_service.build_storyboard(db, ready_project)
    scene = storyboard.scenes[0]
    storyboard_service.set_lock(db, scene, True)
    db.commit()

    with pytest.raises(SceneLocked):
        storyboard_service.update_scene(db, scene, {"lighting": "x"})
    with pytest.raises(SceneLocked):
        storyboard_service.make_cheaper(db, scene)

    storyboard_service.update_scene(db, scene, {"lighting": "forced"}, force=True)
    assert scene.lighting == "forced"


def test_locked_scene_survives_storyboard_regeneration(db, ready_project):
    storyboard = storyboard_service.build_storyboard(db, ready_project)
    scene = storyboard.scenes[0]
    storyboard_service.update_scene(db, scene, {"lighting": "إضاءة مثبتة"})
    storyboard_service.set_lock(db, scene, True)
    db.commit()

    rebuilt = storyboard_service.build_storyboard(db, ready_project, regenerate=True)
    db.commit()
    kept = next(s for s in rebuilt.scenes if s.scene_number == scene.scene_number)
    assert kept.locked is True
    assert kept.lighting == "إضاءة مثبتة"


def test_make_cheaper_moves_down_the_priority_ladder(db, ready_project):
    storyboard = storyboard_service.build_storyboard(db, ready_project)
    scene = storyboard.scenes[-1]
    scene.production_method = ProductionMethod.AI_VIDEO.value
    before = scene.production_method
    storyboard_service.make_cheaper(db, scene)
    db.commit()
    assert scene.production_method != before
    assert scene.estimated_cost_usd < 0.5


# --------------------------------------------------------------------------
# Production plan
# --------------------------------------------------------------------------
def test_production_plan_reports_counts_and_budget_status(db, ready_project):
    storyboard = storyboard_service.build_storyboard(db, ready_project)
    db.commit()
    plan = storyboard.production_plan
    assert plan["scene_count"] == len(storyboard.scenes)
    assert set(plan["counts"]) == {"existing_media", "photo_motion", "ai_image", "ai_video", "motion_graphics"}
    assert plan["status"] in ("safe_to_generate", "budget_approval_required")
    assert plan["generation_order"][0]["priority"] >= plan["generation_order"][-1]["priority"]


def test_continuity_report_runs_all_checks(db, ready_project):
    storyboard = storyboard_service.build_storyboard(db, ready_project)
    report = storyboard.continuity_report
    keys = {c["key"] for c in report["checks"]}
    assert {"colors", "camera_direction", "camera_speed", "lighting", "project_consistency",
            "character_consistency", "music", "pacing", "transitions", "scene_flow"} <= keys


# --------------------------------------------------------------------------
# Iraqi dialect engine
# --------------------------------------------------------------------------
def test_dialect_presets_cover_the_official_six():
    ids = {p["id"] for p in list_presets()}
    assert {
        "iraqi_professional", "iraqi_luxury", "iraqi_emotional",
        "iraqi_direct_sales", "iraqi_friendly", "iraqi_youth",
    } <= ids


def test_number_and_phone_pronunciation():
    assert spell_number_iraqi(150) == "مية وخمسين"
    assert spell_number_iraqi(2000) == "ألفين"
    assert spell_phone("0770-123") .startswith("صفر")


def test_on_screen_text_differs_from_spoken_line():
    spoken = "هسه شوف، بصراحة هذا البيت يجمع العائلة كلها بمكان واحد"
    written = to_on_screen(spoken)
    assert "هسه" not in written and "بصراحة" not in written
    assert len(written.split()) <= 6


def test_forbidden_phrases_are_detected():
    hits = check_forbidden("هذا العرض الأفضل على الإطلاق", preset_name="iraqi_professional")
    assert "الأفضل على الإطلاق" in hits


def test_speech_timing_scales_with_speed():
    text = "بيت يجمع العائلة بمكان هادئ وقريب من كل شي"
    assert estimate_speech_seconds(text, 1.0) > estimate_speech_seconds(text, 1.5)


# --------------------------------------------------------------------------
# Voice
# --------------------------------------------------------------------------
def test_voice_timing_matches_script_duration(db, ready_project):
    voice_service.ensure_demo_voices(db, ready_project.organization_id)
    script = next(s for s in ready_project.scripts if s.is_selected)
    timing = voice_service.voice_timing(db, ready_project, script)
    assert timing[0]["start"] == 0
    assert timing[-1]["end"] == script.total_duration_sec


def test_pronunciation_guide_includes_project_and_phone(db, ready_project):
    guide = voice_service.pronunciation_for_project(db, ready_project)
    assert guide["project_name"]["written"] == ready_project.name
    assert guide["phone"]["spoken"]
