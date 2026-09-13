"""Voice-first timing: captions follow the audio, not the plan.

A caption that lands after the word is the loudest "made by a machine" signal
a vertical ad can give. These tests pin the two things that prevent it: word
timings derived from the *measured* audio, and per-word highlight frames that
stay inside their cue.
"""
from __future__ import annotations

import pytest

from app.media.align import (
    MAX_WORD_SEC,
    MIN_WORD_SEC,
    align_words,
    group_into_cues,
    retime_segments,
    word_weight,
)
from app.core.enums import JobType
from app.media.captions import expand_word_level

SENTENCE = "هسه بمدينة الورد، شقق جاهزة بأسعار تناسبك. اتصل بينا اليوم!"


# --------------------------------------------------------------------------
# Alignment
# --------------------------------------------------------------------------
def test_words_span_exactly_the_measured_audio():
    words = align_words(SENTENCE, 7.4)
    assert words
    assert words[0].start == pytest.approx(0.0, abs=0.01)
    assert words[-1].end == pytest.approx(7.4, abs=0.05), "captions must end with the voice"


@pytest.mark.parametrize("duration", [2.0, 7.4, 31.5])
def test_alignment_holds_at_any_length(duration):
    words = align_words(SENTENCE, duration)
    assert words[-1].end == pytest.approx(duration, abs=0.05)
    assert all(w.end > w.start for w in words)


def test_words_never_overlap_each_other():
    words = align_words(SENTENCE, 7.4)
    for earlier, later in zip(words, words[1:]):
        assert later.start >= earlier.end - 0.001


def test_no_word_flashes_or_lingers():
    """Surplus audio is silence between words, not one word held for seconds.

    The final word is exempt: it holds through the trailing silence so the last
    line stays on screen to the end of the reel instead of vanishing early.
    """
    words = align_words(SENTENCE, 40.0)
    assert all(MIN_WORD_SEC * 0.5 <= w.duration <= MAX_WORD_SEC for w in words[:-1])
    assert words[-1].end == pytest.approx(40.0, abs=0.05)


def test_an_arabic_word_outweighs_its_character_count():
    """Short vowels are unwritten, so characters understate spoken length."""
    assert word_weight("بيت") > 3.0
    # Long vowels are held longer than plain consonants.
    assert word_weight("باب") > word_weight("بتب")


def test_the_definite_article_is_not_its_own_beat():
    assert word_weight("الورد") < word_weight("ورد") + word_weight("ال")


def test_a_provider_alignment_is_trusted_over_our_estimate():
    supplied = [{"word": "هسه", "start": 0.0, "end": 0.9},
                {"word": "أكو", "start": 0.9, "end": 2.4}]
    words = align_words("هسه أكو", 7.4, provider_alignment=supplied)
    assert [w.source for w in words] == ["provider", "provider"]
    assert words[-1].end == pytest.approx(2.4)


def test_empty_text_or_no_audio_produces_nothing_rather_than_guessing():
    assert align_words("", 7.4) == []
    assert align_words(SENTENCE, 0.0) == []


# --------------------------------------------------------------------------
# Cues
# --------------------------------------------------------------------------
def test_cues_break_on_punctuation():
    cues = group_into_cues(align_words(SENTENCE, 7.4))
    assert len(cues) >= 3
    assert cues[0].text.endswith("،")


def test_cues_never_overlap():
    cues = group_into_cues(align_words(SENTENCE, 7.4))
    for earlier, later in zip(cues, cues[1:]):
        assert earlier.end <= later.start + 0.001, "two captions on screen reads as a bug"


def test_a_cue_stays_on_screen_long_enough_to_read():
    for cue in group_into_cues(align_words(SENTENCE, 7.4)):
        assert cue.end - cue.start >= 0.34


def test_estimated_timings_are_labelled_as_estimated():
    cues = group_into_cues(align_words(SENTENCE, 7.4))
    assert all(cue.source == "estimated" for cue in cues)


# --------------------------------------------------------------------------
# Word-level highlight frames
# --------------------------------------------------------------------------
def test_each_word_gets_its_own_highlight_frame():
    cues = [c.as_dict() for c in group_into_cues(align_words(SENTENCE, 7.4))]
    frames = expand_word_level(cues)
    assert len(frames) > len(cues)
    assert all("highlight_index" in f for f in frames)


def test_the_card_text_never_changes_within_a_cue():
    """Only the lit word moves; a card that rewrites itself reads as a glitch."""
    cues = [c.as_dict() for c in group_into_cues(align_words(SENTENCE, 7.4))]
    frames = expand_word_level(cues)
    for cue in cues:
        mine = [f for f in frames if f["start"] >= cue["start"] - 0.01 and f["end"] <= cue["end"] + 0.01]
        assert len({f["text"] for f in mine}) == 1


def test_word_frames_cover_their_cue_without_a_gap():
    cues = [c.as_dict() for c in group_into_cues(align_words(SENTENCE, 7.4))]
    frames = expand_word_level(cues)
    for cue in cues:
        mine = sorted(
            [f for f in frames if f["text"] == cue["text"]], key=lambda f: f["start"]
        )
        assert mine[0]["start"] == pytest.approx(cue["start"], abs=0.01)
        assert mine[-1]["end"] == pytest.approx(cue["end"], abs=0.01)


def test_a_repeated_word_lights_only_once():
    """Matching by string would light both; the index is what fixes it."""
    cue = {
        "text": "اليوم اليوم",
        "start": 0.0,
        "end": 1.6,
        "words": [
            {"word": "اليوم", "start": 0.0, "end": 0.8},
            {"word": "اليوم", "start": 0.8, "end": 1.6},
        ],
    }
    frames = expand_word_level([cue])
    assert [f["highlight_index"] for f in frames] == [0, 1]


def test_a_cue_without_word_timings_passes_through_untouched():
    plain = [{"text": "بدون صوت", "start": 0.0, "end": 2.0}]
    assert expand_word_level(plain) == plain


def test_an_unreadably_short_word_is_folded_into_its_neighbour():
    cue = {
        "text": "أ ب",
        "start": 0.0,
        "end": 1.0,
        "words": [
            {"word": "أ", "start": 0.0, "end": 0.9},
            {"word": "ب", "start": 0.9, "end": 0.92},
        ],
    }
    frames = expand_word_level([cue])
    assert len(frames) == 1
    assert frames[0]["end"] == pytest.approx(1.0)


# --------------------------------------------------------------------------
# Retiming
# --------------------------------------------------------------------------
def test_segments_stretch_onto_the_voice_that_was_produced():
    planned = [{"start": 0.0, "end": 3.0}, {"start": 3.0, "end": 9.0}]
    moved = retime_segments(planned, 12.0)
    assert moved[-1]["end"] == pytest.approx(12.0)
    assert moved[0]["end"] == pytest.approx(4.0)


def test_retiming_a_zero_length_plan_changes_nothing():
    planned = [{"start": 0.0, "end": 0.0}]
    assert retime_segments(planned, 10.0) == planned


# --------------------------------------------------------------------------
# Ordering: the voice must run before the scenes are cut
# --------------------------------------------------------------------------
def test_scene_jobs_wait_for_the_voice(db, make_project, monkeypatch):
    """Cutting a scene before the voice exists cuts it to the estimate.

    The voice job retimes every scene onto the audio it produced. If the scene
    clips were already rendered, they overrun their slots and the finished reel
    is longer than the approved plan — which is exactly how this was found.
    """
    from app.core.enums import ProductionMethod, ProjectState
    from app.models import Scene, ScriptVersion, Storyboard
    from app.services import production as production_service

    project = make_project(name="ترتيب الصوت")
    project.voice_over_enabled = True
    dispatched: list[str] = []
    monkeypatch.setattr(production_service, "dispatch", lambda job_id: dispatched.append(job_id))

    script = ScriptVersion(project_id=project.id, version=1,
                           voice_over_text=SENTENCE, total_duration_sec=20.0)
    db.add(script)
    db.flush()
    storyboard = Storyboard(project_id=project.id, version=1, total_duration_sec=20.0,
                            is_active=True, script_version_id=script.id)
    db.add(storyboard)
    db.flush()
    for number in (1, 2):
        db.add(Scene(
            storyboard_id=storyboard.id, scene_number=number,
            start_time=(number - 1) * 10.0, end_time=number * 10.0,
            production_method=ProductionMethod.PHOTO_MOTION.value,
        ))
    db.commit()

    monkeypatch.setattr(production_service.approval_service, "require_approval", lambda *a, **k: None)
    monkeypatch.setattr(production_service, "active_storyboard", lambda *a, **k: storyboard)
    project.state = ProjectState.GENERATING.value
    db.commit()

    jobs = production_service.start_production(db, project)
    scene_jobs = [j for j in jobs if j.scene_id]
    voice_jobs = [j for j in jobs if j.job_type == JobType.VOICE_GENERATION.value]
    assert scene_jobs and voice_jobs, "the fixture must create both kinds of job"
    # Exactly one job started, and it is the voice.
    assert dispatched == [voice_jobs[0].id], (
        "a scene must not start before the voice has retimed the storyboard"
    )

    # And the voice finishing is what releases them.
    released = production_service.dispatch_jobs_waiting_on_voice(db, project)
    assert released >= len(scene_jobs)
    assert all(j.id in dispatched for j in scene_jobs)


def test_the_caption_box_does_not_breathe_as_the_highlight_moves():
    """Highlighting splits a run and adds a word gap.

    One frame, invisible. Word-level captions draw a frame per word, so the
    box would pulse a few pixels wider and narrower all the way along the line.
    """
    import tempfile

    from PIL import Image

    from app.media.captions import CaptionStyle, render_caption_track

    cues = [c.as_dict() for c in group_into_cues(align_words(SENTENCE, 7.4))]
    rendered = render_caption_track(cues, tempfile.mkdtemp(), style=CaptionStyle(template="bold_bar"))
    by_text: dict[str, list[int]] = {}
    for item in rendered:
        box = Image.open(item["png"]).convert("RGBA").getbbox()
        by_text.setdefault(item["text"], []).append(box[2] - box[0])
    for text, widths in by_text.items():
        assert max(widths) == min(widths), f"caption box jitters across frames of {text!r}"


# --------------------------------------------------------------------------
# Typography: the caption must be still, and it must never show a box
# --------------------------------------------------------------------------
def test_the_line_does_not_move_between_word_frames():
    """The flicker the user reported.

    Highlighting split a token out of its run, changing the number of word gaps
    on the line, so every word after the highlight shifted a few pixels as the
    highlight travelled. Compared on the ALPHA channel: a colour change is the
    highlight working, a geometry change is the tremble.
    """
    import tempfile

    from PIL import Image, ImageChops

    from app.media.captions import CaptionStyle, render_caption_track

    cues = [c.as_dict() for c in group_into_cues(align_words(SENTENCE, 7.4))]
    frames = render_caption_track(cues, tempfile.mkdtemp(), style=CaptionStyle(template="bold_bar"))
    by_text: dict = {}
    for frame in frames:
        by_text.setdefault(frame["text"], []).append(frame["png"])

    for text, pngs in by_text.items():
        if len(pngs) < 2:
            continue
        base = Image.open(pngs[0]).convert("RGBA").split()[-1]
        for png in pngs[1:]:
            other = Image.open(png).convert("RGBA").split()[-1]
            moved = sum(1 for p in ImageChops.difference(base, other).get_flattened_data() if p > 24)
            assert moved == 0, f"caption geometry shifts by {moved}px on {text!r}"


def test_a_face_is_chosen_by_what_it_can_actually_draw():
    """Display faces have the best look and the thinnest coverage.

    Noto Kufi carries no hyphen, colon or Latin percent. Shipping a caption in
    it regardless renders .notdef — an empty box mid-sentence.
    """
    from app.media.captions import arabic_font_for, font_covers

    plain = arabic_font_for("فلل ومجمع سكني متكامل")
    assert "Kufi" in plain, "the heavier display face should win when it can"

    needs_colon = arabic_font_for("اليوم: دفعة أولى")
    assert font_covers(needs_colon, "اليوم:")


def test_no_caption_character_renders_as_an_empty_box():
    """Every glyph the Arabic face is handed must exist in that face."""
    from app.media.captions import (
        _token_script,
        arabic_font_for,
        font_charset,
        normalize_caption_text,
    )

    lines = [
        "- مدينة الزهور فلل ومجمع سكني متكامل",
        "دفعة ٢٥% وأقساط لحد ٤ سنوات",
        "اتصل على 07701234567",
        "احجز اليوم: الفرصة محدودة",
        "مشروع من TADAFQ",
    ]
    for line in lines:
        path = arabic_font_for(line)
        charset = font_charset(path)
        if not charset:
            continue
        drawn = "".join(t for t in normalize_caption_text(line).split() if _token_script(t) == "arabic")
        missing = {ch for ch in drawn if not ch.isspace() and ord(ch) not in charset}
        assert not missing, f"{path} cannot draw {missing} from {line!r}"


def test_standalone_punctuation_is_not_handed_to_the_arabic_face():
    from app.media.captions import _token_script

    assert _token_script("-") == "punct"
    assert _token_script("مدينة") == "arabic"
    assert _token_script("TADAFQ") == "latin"


def test_the_subtitle_template_stays_out_of_the_picture():
    """The restrained broadcast look: no box, small, low in frame.

    A developer's brand film uses this rather than the heavy social bar — the
    photography is the pitch and the caption serves the sound-off viewer.
    """
    from app.media.captions import style_for_template

    subtitle = style_for_template("subtitle")
    bold = style_for_template("bold_bar")
    assert subtitle.box_opacity == 0.0, "a box would defeat the point"
    assert subtitle.font_size < bold.font_size
    assert subtitle.safe_bottom_pct < bold.safe_bottom_pct, "it sits lower"
    assert subtitle.max_lines <= 2


def test_every_caption_template_renders_inside_the_safe_zone():
    from app.media.captions import CAPTION_TEMPLATES, render_caption_png, style_for_template

    for template in CAPTION_TEMPLATES:
        geometry = render_caption_png(
            "وتخيل إنت بمحلات توصل لمشى الواحة",
            f"/tmp/tpl-{template['key']}.png",
            style=style_for_template(template["key"]),
        )
        assert geometry["within_safe_zone"], f"{template['key']} leaves the safe zone"
        assert geometry["rtl"] is True
