"""The caption must not blink.

A word-level cue is ONE card whose highlight moves. Rendering each word as its
own faded overlay cross-dissolves two identical cards once per word: measured in
the rendered file, 40 of 112 frames sat below 60% of full opacity and some went
fully blank. The PNGs were pixel-identical the whole time, which is why this was
invisible until the finished MP4 was measured frame by frame.
"""
from __future__ import annotations

from app.media.captions import expand_word_level
from app.media.overlays import TimedOverlay, build_overlay_graph


def _cue():
    words = [("مدينة", 0.00, 0.42), ("الورد", 0.42, 0.95), ("سكن", 0.95, 1.38),
             ("يليق", 1.38, 1.90)]
    return {
        "text": " ".join(w[0] for w in words),
        "start": 0.0, "end": 1.90,
        "words": [{"word": w, "start": s, "end": e} for w, s, e in words],
    }


# --------------------------------------------------------------------------
# Which frames are the edges of a cue
# --------------------------------------------------------------------------
def test_only_the_first_and_last_word_frame_are_cue_edges():
    frames = expand_word_level([_cue()])
    assert len(frames) == 4
    assert [f["cue_first"] for f in frames] == [True, False, False, False]
    assert [f["cue_last"] for f in frames] == [False, False, False, True]


def test_word_frames_abut_so_the_card_never_disappears():
    frames = expand_word_level([_cue()])
    for earlier, later in zip(frames, frames[1:]):
        assert earlier["end"] == later["start"]
    assert frames[0]["start"] == 0.0 and frames[-1]["end"] == 1.90


# --------------------------------------------------------------------------
# What that turns into in the filtergraph
# --------------------------------------------------------------------------
def test_a_continuation_frame_carries_no_fade_at_all():
    graph, _ = build_overlay_graph(
        [TimedOverlay(png="a.png", start=0.42, end=0.95, fade_in=0.0, fade_out=0.0)]
    )
    assert "fade=" not in graph


def test_the_opening_frame_fades_in_but_not_out():
    graph, _ = build_overlay_graph(
        [TimedOverlay(png="a.png", start=0.0, end=0.42, fade_out=0.0)]
    )
    assert "fade=t=in" in graph
    assert "fade=t=out" not in graph


def test_the_closing_frame_fades_out_but_not_in():
    graph, _ = build_overlay_graph(
        [TimedOverlay(png="a.png", start=1.38, end=1.90, fade_in=0.0)]
    )
    assert "fade=t=out" in graph
    assert "fade=t=in" not in graph


def test_an_ordinary_overlay_still_fades_both_ways():
    """The logo and the CTA card must keep the soft entrance they always had."""
    graph, _ = build_overlay_graph([TimedOverlay(png="logo.png", start=0.0, end=8.0)])
    assert "fade=t=in" in graph and "fade=t=out" in graph


# --------------------------------------------------------------------------
# The boundary frame
# --------------------------------------------------------------------------
def test_the_enable_window_is_half_open():
    """`between` is inclusive at both ends, so two abutting frames both draw on
    the boundary frame. With a stroke-only card that frame renders twice as
    dense — one pulse per word."""
    graph, _ = build_overlay_graph([TimedOverlay(png="a.png", start=0.42, end=0.95)])
    assert "between(t," not in graph
    assert "gte(t,0.420)*lt(t,0.950)" in graph


def test_an_open_ended_overlay_is_unchanged():
    graph, _ = build_overlay_graph([TimedOverlay(png="a.png", start=2.0, end=None)])
    assert "gte(t,2.000)" in graph and "lt(t," not in graph


def test_a_caption_without_word_timings_still_fades_normally():
    plain = expand_word_level([{"text": "مدينة الورد", "start": 0.0, "end": 2.0}])
    assert len(plain) == 1
    assert plain[0].get("cue_first", True) and plain[0].get("cue_last", True)
