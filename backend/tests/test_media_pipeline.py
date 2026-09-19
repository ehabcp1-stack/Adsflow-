"""Media engine tests — these assert on real files, not on mocks.

Every test here runs FFmpeg/Pillow for real and then probes what came out. A
render pipeline that is only unit-tested against fakes will happily ship a
silent, mirrored, letterboxed ad, so the assertions are deliberately about
pixels, streams and durations.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.media.assemble import AssemblySpec, assemble_reel, make_thumbnail
from app.media.audio import AudioMixSpec, attach_audio, measure_loudness, mix_audio
from app.media.captions import (
    CaptionStyle,
    contains_arabic,
    normalize_caption_text,
    render_caption_png,
    render_caption_track,
    resolve_arabic_font,
    shaping_ready,
    style_for_template,
)
from app.media.ffmpeg import capabilities, ffmpeg_available, render_enabled
from app.media.motion import MOTION_PRESETS, recommend_motion, render_photo_motion
from app.media.motion_graphics import render_offer_card, render_offer_scene
from app.media.overlays import BrandLayer, prepare_logo, render_cta_card, render_end_screen, safe_zone
from app.media.probe import probe_media
from app.media.remix import RemixOp, apply_remix, concat_clips, op_from_dict, parse_timecode
from app.media.shots import analyze_video, detect_scene_cuts, split_into_segments

FIXTURES = Path(__file__).parent / "fixtures"
PHOTO = FIXTURES / "photo_landscape.jpg"
PHOTO_PORTRAIT = FIXTURES / "photo_portrait.jpg"
VIDEO = FIXTURES / "sample_video.mp4"
VOICE = FIXTURES / "voice.m4a"
MUSIC = FIXTURES / "music.m4a"
LOGO = FIXTURES / "logo.png"

needs_ffmpeg = pytest.mark.skipif(not ffmpeg_available(), reason="FFmpeg not installed")

#: A real Iraqi ad line: dialect, Arabic-Indic digits, a percent sign and a
#: Latin brand name in one string — everything that breaks naive renderers.
IRAQI_LINE = "هسه صار عندك بيت بمدينة الورد — دفعة أولى ٢٥٪ ويّا TADAFQ"


@pytest.fixture(scope="module")
def fixtures_present() -> None:
    missing = [p.name for p in (PHOTO, VIDEO, VOICE, MUSIC, LOGO) if not p.exists()]
    if missing:
        pytest.skip(f"fixtures missing: {missing} — run python -m tests.fixtures.make_fixtures")


# --------------------------------------------------------------------------
# Probe
# --------------------------------------------------------------------------
def test_probe_reads_real_facts_from_the_file(fixtures_present):
    photo = probe_media(str(PHOTO))
    assert photo.ok and photo.kind == "image"
    assert (photo.width, photo.height) == (1920, 1080)
    assert photo.orientation == "landscape"
    assert photo.duration_sec is None  # a still has no duration

    video = probe_media(str(VIDEO))
    assert video.ok and video.kind == "video"
    assert video.has_audio and video.audio_codec
    assert video.duration_sec == pytest.approx(12.0, abs=0.5)


def test_probe_reports_corruption_instead_of_guessing(tmp_path):
    broken = tmp_path / "broken.jpg"
    broken.write_bytes(b"\xff\xd8\xff\xe0not-an-image-at-all")
    info = probe_media(str(broken))
    assert not info.ok
    assert info.error


def test_probe_detects_portrait(fixtures_present):
    assert probe_media(str(PHOTO_PORTRAIT)).orientation == "portrait"


# --------------------------------------------------------------------------
# Arabic captions
# --------------------------------------------------------------------------
def test_an_arabic_capable_font_is_installed():
    assert resolve_arabic_font() is not None, "install fonts-noto-core"
    assert shaping_ready(), "Arabic shaping needs Pillow+Raqm or arabic-reshaper+python-bidi"


def test_caption_renders_arabic_inside_the_safe_zone(tmp_path):
    out = tmp_path / "caption.png"
    geometry = render_caption_png(IRAQI_LINE, str(out), style=style_for_template("bold_bar"))
    assert out.exists() and out.stat().st_size > 1000
    assert geometry["rtl"] is True
    assert geometry["within_safe_zone"] is True
    assert geometry["block_top"] >= geometry["safe_top"]
    assert geometry["block_bottom"] <= geometry["safe_bottom"]
    assert 1 <= geometry["line_count"] <= 3


def test_caption_png_actually_has_ink(tmp_path):
    from PIL import Image

    out = tmp_path / "ink.png"
    render_caption_png("اتصل بينه هسه", str(out), style=style_for_template("clean_line"))
    alpha = Image.open(out).convert("RGBA").getchannel("A")
    assert alpha.getbbox() is not None, "caption PNG is blank"


def test_caption_wrapping_never_strands_one_word(tmp_path):
    long_line = "وحدات سكنية بمساحات مئة وخمسين ومئتين متر مربع بموقع قريب من المدارس"
    geometry = render_caption_png(long_line, str(tmp_path / "wrap.png"),
                                  style=CaptionStyle(font_size=62))
    if geometry["line_count"] > 1:
        assert len(geometry["lines"][-1].split()) > 1


def test_caption_normalisation_replaces_glyphs_fonts_lack():
    assert "—" not in normalize_caption_text("مدينة — الورد")
    assert "…" not in normalize_caption_text("هسه…")


def test_latin_inside_arabic_uses_a_latin_font(tmp_path):
    geometry = render_caption_png("اتصل بـ TADAFQ اليوم", str(tmp_path / "mixed.png"))
    assert geometry["latin_font"], "mixed-script captions need a Latin fallback font"
    assert contains_arabic("اتصل") and not contains_arabic("TADAFQ")


def test_caption_track_renders_every_line(tmp_path):
    captions = [{"text": "سطر أول", "start": 0, "end": 2},
                {"text": "سطر ثاني", "start": 2, "end": 4},
                {"text": "   ", "start": 4, "end": 5}]
    rendered = render_caption_track(captions, str(tmp_path / "track"))
    assert len(rendered) == 2  # the blank line is dropped, not rendered empty
    assert all(Path(item["png"]).exists() for item in rendered)


# --------------------------------------------------------------------------
# Photo motion
# --------------------------------------------------------------------------
@needs_ffmpeg
def test_photo_motion_produces_a_real_vertical_clip(tmp_path, fixtures_present):
    out = tmp_path / "motion.mp4"
    result = render_photo_motion(str(PHOTO), str(out), duration_sec=2.5, motion="ken_burns")
    info = probe_media(str(out))
    assert info.ok and info.kind == "video"
    assert (info.width, info.height) == (1080, 1920)
    assert info.duration_sec == pytest.approx(2.5, abs=0.25)
    assert info.has_audio, "scene clips carry a silent track so concat never mismatches"
    assert result["motion"] == "ken_burns"


@needs_ffmpeg
def test_photo_motion_actually_moves(tmp_path, fixtures_present):
    """A 'motion' clip whose first and last frame are identical is a still."""
    from PIL import Image

    from app.media.ffmpeg import run_ffmpeg

    clip = tmp_path / "move.mp4"
    render_photo_motion(str(PHOTO), str(clip), duration_sec=2.0, motion="push_in")
    frames = []
    for index, frame_no in enumerate((1, 55)):
        png = tmp_path / f"f{index}.png"
        run_ffmpeg(["-i", str(clip), "-vf", f"select=eq(n\\,{frame_no})", "-vsync", "0",
                    "-frames:v", "1", str(png)], label="frame")
        frames.append(Image.open(png).convert("L").resize((64, 64)))
    a, b = list(frames[0].tobytes()), list(frames[1].tobytes())
    difference = sum(abs(x - y) for x, y in zip(a, b)) / (64 * 64 * 255)
    assert difference > 0.002, "push_in produced a static clip"


def test_motion_recommendation_respects_the_material():
    assert recommend_motion(index=0, is_hook=True) == "push_in"
    assert recommend_motion(index=3, purpose="offer") == "controlled_zoom"
    assert recommend_motion(index=1, orientation="portrait", motion_potential=0.9) == "tilt_up"
    assert recommend_motion(index=2, motion_potential=0.1) == "controlled_zoom"


def test_every_motion_preset_stays_gentle():
    """Aggressive movement is what makes a slideshow ad look cheap."""
    for preset in MOTION_PRESETS.values():
        assert max(preset.zoom_from, preset.zoom_to) <= 1.20
        assert abs(preset.pan_x) <= 1.0 and abs(preset.pan_y) <= 1.0


# --------------------------------------------------------------------------
# Remix
# --------------------------------------------------------------------------
@needs_ffmpeg
def test_remix_trims_reframes_and_mutes(tmp_path, fixtures_present):
    out = tmp_path / "remix.mp4"
    result = apply_remix(str(VIDEO), str(out),
                         op_from_dict({"op": "trim", "start": 1.0, "end": 4.0,
                                       "reframe": "crop", "look": "warm_film", "mute": True}))
    info = probe_media(str(out))
    assert (info.width, info.height) == (1080, 1920)
    assert info.duration_sec == pytest.approx(3.0, abs=0.3)
    assert result["audio_kept"] is False


@needs_ffmpeg
def test_remix_speed_change_shortens_the_clip(tmp_path, fixtures_present):
    out = tmp_path / "fast.mp4"
    apply_remix(str(VIDEO), str(out),
                op_from_dict({"op": "speed", "start": 0, "end": 4, "speed": 2.0}))
    assert probe_media(str(out)).duration_sec == pytest.approx(2.0, abs=0.3)


@needs_ffmpeg
def test_blur_pad_reframe_keeps_the_whole_frame(tmp_path, fixtures_present):
    out = tmp_path / "blur.mp4"
    apply_remix(str(VIDEO), str(out),
                op_from_dict({"op": "reframe", "start": 0, "end": 2, "reframe": "blur_pad"}))
    info = probe_media(str(out))
    assert (info.width, info.height) == (1080, 1920)


def test_timecodes_parse_in_every_shape_a_brief_uses():
    assert parse_timecode("0:12.5") == pytest.approx(12.5)
    assert parse_timecode("12.5") == pytest.approx(12.5)
    assert parse_timecode(12.5) == pytest.approx(12.5)
    assert parse_timecode(None) is None
    assert parse_timecode("nonsense") is None


@needs_ffmpeg
def test_concat_joins_mismatched_clips(tmp_path, fixtures_present):
    """The demuxer path silently breaks on parameter mismatch; ours must not."""
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    render_photo_motion(str(PHOTO), str(a), duration_sec=1.5, motion="push_in")
    apply_remix(str(VIDEO), str(b), RemixOp(op="trim", start=0, end=1.5, reframe="blur_pad"))
    out = tmp_path / "joined.mp4"
    result = concat_clips([str(a), str(b)], str(out))
    info = probe_media(str(out))
    assert result["clips"] == 2
    assert info.duration_sec == pytest.approx(3.0, abs=0.5)
    assert info.has_audio and (info.width, info.height) == (1080, 1920)


# --------------------------------------------------------------------------
# Shots
# --------------------------------------------------------------------------
@needs_ffmpeg
def test_shot_detection_finds_the_real_cuts(fixtures_present):
    cuts = detect_scene_cuts(str(VIDEO))
    assert len(cuts) == 2
    assert cuts[0] == pytest.approx(4.0, abs=0.3)
    assert cuts[1] == pytest.approx(8.0, abs=0.3)


@needs_ffmpeg
def test_shot_analysis_scores_and_recommends(tmp_path, fixtures_present):
    report = analyze_video(str(VIDEO), thumb_dir=str(tmp_path))
    assert report["ok"] and report["segment_count"] == 3
    assert report["best_opening_index"] is not None
    for segment in report["segments"]:
        assert 0.0 <= segment["quality"] <= 1.0
        assert 0.0 <= segment["hook_potential"] <= 1.0
        assert segment["recommendation"] in {"keep", "trim", "drop"}
        assert segment["reason_ar"]
        assert segment["thumbnail"] and Path(segment["thumbnail"]).exists()


def test_flash_frames_are_absorbed_not_kept():
    segments = split_into_segments(10.0, [0.2, 4.0, 4.1, 9.9])
    assert all(end - start >= 0.4 for start, end in segments)
    assert segments[0][0] == 0.0 and segments[-1][1] == 10.0


def test_long_shots_are_split_into_usable_lengths():
    segments = split_into_segments(30.0, [])
    assert len(segments) > 1
    assert all(end - start <= 8.1 for start, end in segments)


# --------------------------------------------------------------------------
# Audio
# --------------------------------------------------------------------------
@needs_ffmpeg
def test_audio_mix_ducks_music_and_masters_loudness(tmp_path, fixtures_present):
    out = tmp_path / "mix.m4a"
    result = mix_audio(
        AudioMixSpec(voice_path=str(VOICE), music_path=str(MUSIC), duration_sec=10.0),
        str(out),
    )
    assert result["sources"] == ["voice", "music"]
    assert result["ducked"] is True
    loudness = measure_loudness(str(out))
    if loudness.get("available"):
        assert -22.0 < loudness["integrated_lufs"] < -8.0


@needs_ffmpeg
def test_a_muted_reel_still_gets_a_valid_audio_stream(tmp_path):
    out = tmp_path / "silent.m4a"
    result = mix_audio(AudioMixSpec(duration_sec=3.0), str(out))
    assert result["silent"] is True
    assert probe_media(str(out)).has_audio


@needs_ffmpeg
def test_attach_audio_muxes_without_touching_the_picture(tmp_path, fixtures_present):
    clip = tmp_path / "clip.mp4"
    render_photo_motion(str(PHOTO), str(clip), duration_sec=2.0, motion="static")
    out = tmp_path / "muxed.mp4"
    attach_audio(str(clip), str(VOICE), str(out), duration_sec=2.0)
    info = probe_media(str(out))
    assert info.has_audio and (info.width, info.height) == (1080, 1920)


# --------------------------------------------------------------------------
# Brand overlays
# --------------------------------------------------------------------------
def _brand() -> BrandLayer:
    return BrandLayer(
        name="مدينة الورد", logo_path=str(LOGO), primary_color="#0F172A",
        secondary_color="#2563EB", phone="٠٧٧٠ ١٢٣ ٤٥٦٧", website="tadafq.com",
        social_handle="@tadafq", cta_text="احجز وحدتك هسه", tagline="سكن ذكي بقلب بغداد",
    )


def test_cta_card_stays_out_of_the_platform_chrome(tmp_path, fixtures_present):
    info = render_cta_card(str(tmp_path / "cta.png"), _brand(),
                           cta_text="احجز وحدتك هسه", platform="tiktok")
    assert Path(info["path"]).exists()
    assert info["within_safe_zone"]
    assert info["pill_bottom"] <= 1920 - int(1920 * safe_zone("tiktok")["bottom"]) + 1


def test_end_screen_carries_the_brand_not_ours(tmp_path, fixtures_present):
    info = render_end_screen(str(tmp_path / "end.png"), _brand())
    assert info["has_logo"] and info["contact_lines"] == 3 and info["fits"]


def test_logo_is_normalised_not_used_raw(tmp_path, fixtures_present):
    from PIL import Image

    out = prepare_logo(str(LOGO), str(tmp_path / "logo.png"), max_width=200, opacity=0.8)
    assert out and Image.open(out).width == 200


def test_missing_logo_degrades_instead_of_raising(tmp_path):
    assert prepare_logo("/does/not/exist.png", str(tmp_path / "x.png")) is None


# --------------------------------------------------------------------------
# Motion graphics
# --------------------------------------------------------------------------
def test_offer_card_is_typography_not_a_generated_video(tmp_path):
    info = render_offer_card(str(tmp_path / "offer.png"),
                             headline="دفعة أولى ٢٥٪",
                             lines=["وأقساط لحد ٤ سنوات", "تسليم خلال ٦ أشهر"],
                             footnote="مدينة الورد")
    assert Path(info["path"]).exists() and info["lines"] == 4


@needs_ffmpeg
def test_offer_scene_animates_the_card(tmp_path):
    out = tmp_path / "offer.mp4"
    result = render_offer_scene(str(out), headline="دفعة أولى ٢٥٪", duration_sec=2.0)
    info = probe_media(str(out))
    assert (info.width, info.height) == (1080, 1920)
    assert result["production_method"] == "motion_graphics"


# --------------------------------------------------------------------------
# Full assembly
# --------------------------------------------------------------------------
@needs_ffmpeg
def test_assemble_produces_a_finished_reel(tmp_path, fixtures_present):
    """The acceptance test: photos + voice + music -> one real MP4."""
    clips = []
    for index, (photo, motion) in enumerate(
        ((PHOTO, "push_in"), (PHOTO_PORTRAIT, "tilt_up"))
    ):
        clip = tmp_path / f"scene{index}.mp4"
        render_photo_motion(str(photo), str(clip), duration_sec=2.5, motion=motion)
        clips.append(str(clip))

    spec = AssemblySpec(
        scene_clips=clips,
        captions=[{"text": "هسه صار عندك بيت بمدينة الورد", "start": 0.0, "end": 2.5},
                  {"text": "دفعة أولى ٢٥٪ وأقساط لحد ٤ سنوات", "start": 2.5, "end": 5.0}],
        caption_style=style_for_template("bold_bar"),
        brand=_brand(), cta_text="احجز وحدتك هسه",
        voice_path=str(VOICE), music_path=str(MUSIC), end_screen_sec=1.5,
    )
    out = tmp_path / "reel.mp4"
    report = assemble_reel(spec, str(out), work_dir=str(tmp_path / "work"))

    info = probe_media(str(out))
    assert info.ok and info.kind == "video"
    assert (info.width, info.height) == (1080, 1920)
    assert info.has_audio and (info.video_codec or "").lower() in {"h264", "avc1"}
    assert info.duration_sec == pytest.approx(6.5, abs=0.8)  # 2.5 + 2.5 + end screen

    overlays = report["stages"]["overlays"]
    assert overlays["logo"] and overlays["cta"] and overlays["end_screen"]
    assert len(overlays["captions"]) >= 1
    assert all(caption["within_safe_zone"] for caption in overlays["captions"])
    assert all(caption["rtl"] for caption in overlays["captions"])
    assert report["stages"]["audio"]["ducked"] is True
    assert not report["warnings"]


@needs_ffmpeg
def test_captions_never_stack_on_the_cta(tmp_path, fixtures_present):
    clip = tmp_path / "one.mp4"
    render_photo_motion(str(PHOTO), str(clip), duration_sec=4.0, motion="static")
    spec = AssemblySpec(
        scene_clips=[str(clip)],
        captions=[{"text": "نص يمتد لآخر الريل", "start": 0.0, "end": 4.0}],
        brand=_brand(), cta_text="احجز وحدتك هسه",
        end_screen_enabled=False, cta_lead_sec=1.5,
    )
    report = assemble_reel(spec, str(tmp_path / "r.mp4"), work_dir=str(tmp_path / "w"))
    captions = report["stages"]["overlays"]["captions"]
    if captions:
        assert max(c["end"] for c in captions) <= 4.0 - 1.5 + 0.01


@needs_ffmpeg
def test_assembly_refuses_to_invent_a_reel_from_nothing(tmp_path):
    with pytest.raises(ValueError):
        assemble_reel(AssemblySpec(scene_clips=[]), str(tmp_path / "x.mp4"))


@needs_ffmpeg
def test_thumbnail_is_a_real_frame(tmp_path, fixtures_present):
    clip = tmp_path / "clip.mp4"
    render_photo_motion(str(PHOTO), str(clip), duration_sec=2.0, motion="push_in")
    out = make_thumbnail(str(clip), str(tmp_path / "thumb.png"), at_sec=1.0)
    assert out and Path(out).exists()
    info = probe_media(out)
    assert (info.width, info.height) == (1080, 1920)


# --------------------------------------------------------------------------
# Capability honesty
# --------------------------------------------------------------------------
def test_capabilities_are_probed_never_assumed():
    caps = capabilities()
    if ffmpeg_available():
        assert caps.available and caps.version
        # These are the filters the pipeline actually relies on.
        for name in ("zoompan", "overlay", "crop", "scale", "concat", "amix"):
            assert caps.has_filter(name), f"missing filter: {name}"
        assert caps.has_encoder("libx264") and caps.has_encoder("aac")
    else:
        assert not caps.available


def test_render_enabled_follows_the_setting(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENABLE_LOCAL_RENDER", False)
    assert render_enabled() is False


def test_the_overlay_burn_is_split_so_its_memory_has_a_ceiling(tmp_path, monkeypatch):
    """One FFmpeg call per chunk, and no intermediates left behind.

    Every overlay is a `-loop 1 -i <png>`, all alive at once, so this stage's
    memory is linear in the overlay count — measured at ~14 MB per input after
    cropping, on top of ~165 MB. Word-level captions make one overlay per
    word, so the count follows the script: on the live server FFmpeg was
    killed mid-burn and the reel came back a placeholder with
    `assemble:overlays failed (exit -9)`.
    """
    from app.media import assemble
    from app.media.overlays import TimedOverlay

    calls: list = []

    def fake_run(args, *, label, timeout=None):
        calls.append({"label": label, "out": args[-1], "inputs": args.count("-loop")})
        Path(args[-1]).write_bytes(b"x")
        return ""

    monkeypatch.setattr(assemble, "run_ffmpeg", fake_run)
    monkeypatch.setattr(assemble, "OVERLAY_CHUNK", 4)

    source = tmp_path / "picture.mp4"
    source.write_bytes(b"x")
    overlays = [TimedOverlay(png=f"{tmp_path}/o{i}.png", start=float(i), end=float(i) + 1)
                for i in range(10)]
    out = tmp_path / "burned.mp4"

    assemble._burn_overlays(str(source), overlays, str(out), duration=10.0)

    assert len(calls) == 3, "ten overlays in chunks of four is three passes"
    assert [c["inputs"] for c in calls] == [4, 4, 2]
    assert calls[-1]["out"] == str(out), "the last pass writes the real output"
    # Intermediates are cleaned up; only the finished file survives.
    assert not list(tmp_path.glob("*.pass*.mp4"))
    assert out.exists()


def test_a_single_chunk_still_runs_as_one_pass(tmp_path, monkeypatch):
    """Nothing is re-encoded twice when it does not need to be."""
    from app.media import assemble
    from app.media.overlays import TimedOverlay

    calls: list = []
    monkeypatch.setattr(assemble, "run_ffmpeg",
                        lambda args, *, label, timeout=None: (calls.append(label),
                                                              Path(args[-1]).write_bytes(b"x"), "")[-1])
    monkeypatch.setattr(assemble, "OVERLAY_CHUNK", 24)

    source = tmp_path / "picture.mp4"
    source.write_bytes(b"x")
    assemble._burn_overlays(
        str(source),
        [TimedOverlay(png=f"{tmp_path}/o{i}.png", start=0.0, end=1.0) for i in range(3)],
        str(tmp_path / "out.mp4"),
        duration=3.0,
    )
    assert calls == ["assemble:overlays"], "one pass keeps the plain label"


def test_a_named_transition_is_actually_drawn():
    """`concat_clips` took this argument from day one and never used it.

    Every editing style names a transition — soft_dissolve, whip_pan — the
    timeline stored it and the report printed it, and the filtergraph was a
    plain `concat`. Every cut in every ad was hard, which is most of why a
    reel of stills read as a slideshow.
    """
    from app.media.remix import xfade_effect

    assert xfade_effect("soft_dissolve") == "fade"
    assert xfade_effect("whip_pan") == "slideleft"
    # A match cut IS a hard cut — two shots that line up. Not a dissolve.
    assert xfade_effect("match_cut") is None
    assert xfade_effect("cut") is None
    assert xfade_effect(None) is None


def test_a_dissolve_does_not_shorten_the_reel():
    """The picture has to stay on the voice it was cut to.

    An overlap of `d` normally eats `d` out of the running time, which would
    slide every scene off the voice-over — and the captions are timed to that
    voice. Each outgoing clip is padded by `d` first, so the dissolve consumes
    the padding and the finished reel is the length it would have been with
    hard cuts.
    """
    from app.media.remix import _xfade_chain

    durations = [4.0, 5.0, 4.5, 6.0]
    chain = _xfade_chain(len(durations), durations, "fade", 0.35)
    text = " ".join(chain)
    assert text.count("tpad") == len(durations) - 1, "every outgoing clip is padded"
    # The offsets are the cumulative un-padded durations — that is what keeps
    # the total the same.
    for offset in ("offset=4.000", "offset=9.000", "offset=13.500"):
        assert offset in text
    assert chain[-1].endswith("[v]")


def test_a_clip_too_short_for_its_dissolve_cuts_instead(tmp_path, monkeypatch):
    """More dissolve than picture is worse than a cut, so it says so."""
    from app.media import remix

    class _Info:
        duration_sec = 0.4
        width = 1080
        height = 1920
        size_bytes = 1234

    monkeypatch.setattr(remix, "probe_media", lambda _p: _Info())
    calls = []
    monkeypatch.setattr(remix, "run_ffmpeg", lambda args, **kw: calls.append(args))
    for name in ("a.mp4", "b.mp4"):
        (tmp_path / name).write_bytes(b"x")

    result = remix.concat_clips([str(tmp_path / "a.mp4"), str(tmp_path / "b.mp4")],
                                str(tmp_path / "out.mp4"),
                                transition="soft_dissolve", transition_sec=0.35)
    assert result["transition"] == "cut"
    assert result["transition_requested"] == "soft_dissolve"
    assert "xfade" not in " ".join(calls[0])


def test_every_editing_style_names_a_transition_the_renderer_can_draw():
    """A style may not ask for something the engine cannot construct.

    `emotional_cinematic` named `match_cut` — two shots whose framing lines
    up, which this engine does not do; it cuts between stills. So the most
    cinematic style in the product drew plain hard cuts, which is exactly the
    slideshow feel that started this work. `cut` is a real choice; a name the
    renderer silently turns into a cut is not.
    """
    from app.media.remix import xfade_effect
    from app.services.editing import EDITING_STYLES

    for style in EDITING_STYLES:
        transition = style["transition"]
        assert transition == "cut" or xfade_effect(transition), (
            f"{style['key']} asks for {transition!r}, which nothing draws"
        )
