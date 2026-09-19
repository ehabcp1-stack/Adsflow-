"""What the model is allowed to say, and what happens when it says something else.

A live run produced a reel with no moving picture in it, and every component
along the way reported success. The storyboard came back with
`production_method: "kenburns_zoom_on_photo"` — descriptive, plausible, and in
no enum anywhere. It missed `LOCAL_METHODS`, so four scenes that should have
been rendered from the customer's own photograph with FFmpeg, for nothing, were
handed to the image provider instead. That provider is the mock on that server,
so it returned four SVG stills, marked them `passed` at quality 95, and the
assembler — finding no clips to join — produced a placeholder. QC then scored
the placeholder 61 out of 100 and listed complaints about its resolution.

The QC report had the same disease from the other end: `scores` was
`Dict[str, float]`, so the model answered in its own vocabulary on its own
scale (`dialect_authenticity: 0.92`, `overall: 0.68`) and the one key that did
match a real dimension, `brand_consistency: 0`, meant nought percent and was
read as nought out of a hundred.

One cause, two symptoms: a contract that accepts anything is not a contract.
These tests hold both ends shut.
"""
from __future__ import annotations

import pytest

from app.core.enums import ProductionMethod
from app.providers import model_router
from app.providers.schemas import QC_DIMENSIONS, validate_llm_json

#: The exact storyboard value from the live project, kept verbatim.
LIVE_BAD_METHOD = "kenburns_zoom_on_photo"
#: The exact QC scores payload from the live project, kept verbatim.
LIVE_BAD_SCORES = {
    "dialect_authenticity": 0.92,
    "content_quality": 0.82,
    "cta_clarity": 0.55,
    "brand_consistency": 0,
    "compliance": 0.75,
    "overall": 0.68,
}


def _scene(method: str) -> dict:
    return {
        "scene_number": 1, "start_time": 0.0, "end_time": 3.0,
        "purpose": "hook", "voice_line": "شوف هالشي", "visual_source": "asset",
        "visual_direction": "d", "camera_direction": "c", "camera_movement": "push_in",
        "lighting": "soft", "on_screen_text": "نص", "text_animation": "fade",
        "music_instruction": "m", "sfx_instruction": "s", "transition": "cut",
        "production_method": method,
    }


def _scores(value: float) -> dict:
    return {key: value for key in QC_DIMENSIONS}


# --------------------------------------------------------------------------
# Production method
# --------------------------------------------------------------------------
def test_the_storyboard_rejects_a_method_nothing_implements():
    ok, _instance, errors = validate_llm_json("storyboard", {"scenes": [_scene(LIVE_BAD_METHOD)]})
    assert not ok
    assert any(LIVE_BAD_METHOD in error for error in errors)


@pytest.mark.parametrize("method", [m.value for m in ProductionMethod])
def test_every_real_method_is_accepted(method):
    ok, _instance, errors = validate_llm_json("storyboard", {"scenes": [_scene(method)]})
    assert ok, errors


def test_the_router_ignores_a_requested_method_it_does_not_know():
    """An unknown request must not beat the cost-first ladder.

    `choose_method` returned `requested_method` unconditionally, labelled
    "اختيار يدوي من المستخدم" — a user's manual choice. It was nothing of the
    kind: it came from the storyboard payload, which a model writes.
    """
    method, _reason = model_router.choose_method(
        has_original_video=False, has_original_photo=True,
        is_hero=False, is_hook=True, requested_method=LIVE_BAD_METHOD,
    )
    assert method == ProductionMethod.PHOTO_MOTION.value

    honoured, _reason = model_router.choose_method(
        has_original_video=False, has_original_photo=True,
        is_hero=False, is_hook=True, requested_method=ProductionMethod.ORIGINAL_PHOTO.value,
    )
    assert honoured == ProductionMethod.ORIGINAL_PHOTO.value


def test_a_legacy_scene_is_repaired_rather_than_handed_to_a_provider(db, make_project):
    """Storyboards written before the schema existed still have to produce.

    Regenerating would fix the label and throw away the approvals with it, so
    the method is re-derived from what the scene actually has.
    """
    from app.models import Scene, Storyboard
    from app.services.production import repair_production_method

    project = make_project(name="ستوري بورد قديم")
    storyboard = Storyboard(project_id=project.id, version=1, total_duration_sec=15.0)
    db.add(storyboard)
    db.flush()
    scene = Scene(
        storyboard_id=storyboard.id, scene_number=1, start_time=0.0, end_time=3.0,
        production_method=LIVE_BAD_METHOD, is_hook=True,
    )
    db.add(scene)
    db.flush()

    previous = repair_production_method(db, project, scene)
    assert previous == LIVE_BAD_METHOD
    assert scene.production_method in {m.value for m in ProductionMethod}
    # And a scene that was already fine is left exactly alone.
    assert repair_production_method(db, project, scene) is None


# --------------------------------------------------------------------------
# QC scores
# --------------------------------------------------------------------------
def test_the_live_scores_payload_is_refused():
    ok, _instance, errors = validate_llm_json("qc", {"scores": LIVE_BAD_SCORES})
    assert not ok
    missing = {dimension for dimension in QC_DIMENSIONS if dimension != "brand_consistency"}
    assert all(any(name in error for error in errors) for name in missing)


def test_a_zero_to_one_answer_is_read_as_a_percentage():
    """0.92 means 92, and the one time it did not cost ten points of score."""
    ok, instance, errors = validate_llm_json("qc", {"scores": _scores(0.92)})
    assert ok, errors
    assert instance.scores.visual_quality == 92.0
    assert instance.scores.brand_consistency == 92.0


def test_a_zero_to_hundred_answer_is_left_alone():
    ok, instance, errors = validate_llm_json("qc", {"scores": _scores(88)})
    assert ok, errors
    assert instance.scores.visual_quality == 88.0


def test_a_mixed_scale_is_not_guessed_at():
    """Half in one unit and half in another is a model contradicting itself."""
    payload = _scores(90)
    payload["brand_consistency"] = 0.4
    ok, instance, _errors = validate_llm_json("qc", {"scores": payload})
    assert ok
    assert instance.scores.brand_consistency == 0.4, "no rescaling on a mixed answer"


def test_dimensions_the_model_invented_never_reach_the_score():
    payload = {**_scores(90), "dialect_authenticity": 0.92, "overall": 0.68}
    ok, instance, errors = validate_llm_json("qc", {"scores": payload})
    assert ok, errors
    assert set(instance.scores.model_dump()) == set(QC_DIMENSIONS)


def test_a_score_outside_the_scale_is_refused():
    payload = _scores(90)
    payload["visual_quality"] = 140
    ok, _instance, errors = validate_llm_json("qc", {"scores": payload})
    assert not ok and errors


# --------------------------------------------------------------------------
# What the screen says
# --------------------------------------------------------------------------
def test_a_failed_check_does_not_print_the_sentence_for_passing():
    """The panel is the one place the words have to be trustworthy.

    A reel with no sound listed, in red, "الريل بيه مسار صوتي" — the reel has
    an audio track.
    """
    from app.services.qc_checks import _check

    passed = _check("has_audio_track", True, "critical",
                    "The reel has an audio track.", "الريل بيه مسار صوتي.",
                    fail_en="The reel has no audio track at all.",
                    fail_ar="الريل بدون مسار صوتي أبداً.")
    failed = _check("has_audio_track", False, "critical",
                    "The reel has an audio track.", "الريل بيه مسار صوتي.",
                    fail_en="The reel has no audio track at all.",
                    fail_ar="الريل بدون مسار صوتي أبداً.")

    assert passed["message_ar"] == "الريل بيه مسار صوتي."
    assert failed["message_ar"] == "الريل بدون مسار صوتي أبداً."
    assert failed["message_en"] != passed["message_en"]
    assert failed["severity"] == "critical" and passed["severity"] == "info"


def test_every_boolean_check_carries_a_failure_sentence():
    """A guard for the next one added in a hurry.

    Any check whose message does not contain its own measurement reads as an
    assertion, and an assertion shown on failure is a lie. Checks that
    interpolate what they measured ("the frame is 540x960") are exempt because
    they read correctly either way.
    """
    import ast
    import pathlib

    source = pathlib.Path("app/services/qc_checks.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    offenders = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_check"):
            continue
        if len(node.args) < 5:
            continue
        code = node.args[0].value if isinstance(node.args[0], ast.Constant) else "?"
        passed_expr = node.args[1]
        # A check hard-coded to False only ever renders its failure message.
        if isinstance(passed_expr, ast.Constant) and passed_expr.value is False:
            continue
        interpolated = any(isinstance(arg, ast.JoinedStr) for arg in node.args[3:5])
        has_fail = any(kw.arg in ("fail_en", "fail_ar") for kw in node.keywords)
        if not interpolated and not has_fail:
            offenders.append(code)
    assert not offenders, f"these checks would print the passing sentence on failure: {offenders}"


def test_a_placeholder_reel_is_named_as_one_before_anything_else(db, make_project):
    """Capping two dimensions at 60 was the whole of the old answer.

    So a reel containing no footage came back as "61 — needs fixing" beside a
    list of complaints about its resolution and its captions: every one true,
    none of them the point.
    """
    from app.services.qc import PLACEHOLDER_ISSUE, CRITICAL_CODES

    assert PLACEHOLDER_ISSUE["code"] in CRITICAL_CODES
    assert PLACEHOLDER_ISSUE["severity"] == "critical"
    assert "بديل" in PLACEHOLDER_ISSUE["message_ar"]
