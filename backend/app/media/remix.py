"""Existing Video Remix — real operations on footage the customer owns.

The product rule is that original footage beats generated footage whenever it
can carry the scene. That is only true if we can actually cut, reframe, pace
and grade it, which is what this module does with FFmpeg.

Every operation writes a new file; the customer's original is never modified.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from app.media.ffmpeg import (
    AUDIO_ENCODE,
    INTERMEDIATE_VIDEO_ENCODE,
    OUT_FPS,
    OUT_HEIGHT,
    OUT_WIDTH,
    VIDEO_ENCODE,
    capabilities,
    color_look,
    ensure_parent,
    run_ffmpeg,
)
from app.media.probe import probe_media

log = logging.getLogger("adflow.media.remix")

#: The operation vocabulary shown in the UI and stored on Scene.remix_ops.
REMIX_OPERATIONS: List[Dict[str, Any]] = [
    {"key": "keep", "label_en": "Keep", "label_ar": "احتفظ", "real": True},
    {"key": "trim", "label_en": "Trim", "label_ar": "قص", "real": True},
    {"key": "reorder", "label_en": "Reorder", "label_ar": "إعادة ترتيب", "real": True},
    {"key": "speed", "label_en": "Speed", "label_ar": "سرعة", "real": True},
    {"key": "reframe", "label_en": "Reframe 9:16", "label_ar": "إعادة تأطير ٩:١٦", "real": True},
    {"key": "crop", "label_en": "Crop", "label_ar": "اقتصاص", "real": True},
    {"key": "color_grade", "label_en": "Color Grade", "label_ar": "تدرج لوني", "real": True},
    {"key": "stabilize", "label_en": "Stabilize", "label_ar": "تثبيت", "real": capabilities().has_filter("deshake")},
    {"key": "remove_audio", "label_en": "Remove Original Audio", "label_ar": "حذف الصوت الأصلي", "real": True},
    {"key": "add_voice", "label_en": "Add New Voice Over", "label_ar": "إضافة تعليق صوتي", "real": True},
    {"key": "add_captions", "label_en": "Add Captions", "label_ar": "إضافة كابشن", "real": True},
    {"key": "add_branding", "label_en": "Add Branding", "label_ar": "إضافة الهوية", "real": True},
    {"key": "add_music", "label_en": "Add Music", "label_ar": "إضافة موسيقى", "real": True},
    {"key": "add_sfx", "label_en": "Add SFX", "label_ar": "إضافة مؤثرات", "real": True},
    {"key": "ai_enhance", "label_en": "AI Enhance", "label_ar": "تحسين بالذكاء", "real": False},
    {"key": "video_to_video", "label_en": "Video-to-Video", "label_ar": "تحويل فيديو لفيديو", "real": False},
]

REFRAME_MODES = ("crop", "blur_pad", "contain")


@dataclass
class RemixOp:
    """One instruction from the remix plan."""

    op: str = "keep"
    start: Optional[float] = None
    end: Optional[float] = None
    speed: float = 1.0
    reframe: str = "crop"
    #: 0.0 = focus on the left/top edge, 0.5 = centre, 1.0 = right/bottom edge.
    focus_x: float = 0.5
    focus_y: float = 0.5
    look: str = "neutral"
    stabilize: bool = False
    mute: bool = True
    fade_in: float = 0.0
    fade_out: float = 0.0
    notes: Dict[str, Any] = field(default_factory=dict)


def _focus_crop(target_w: int, target_h: int, focus_x: float, focus_y: float) -> str:
    """Crop to the target aspect, biased toward the interesting part of frame."""
    fx = min(max(focus_x, 0.0), 1.0)
    fy = min(max(focus_y, 0.0), 1.0)
    return (
        f"crop='min(iw,ih*{target_w}/{target_h})':'min(ih,iw*{target_h}/{target_w})'"
        f":'(iw-out_w)*{fx:.3f}':'(ih-out_h)*{fy:.3f}'"
    )


def build_reframe_chain(
    mode: str,
    *,
    width: int = OUT_WIDTH,
    height: int = OUT_HEIGHT,
    focus_x: float = 0.5,
    focus_y: float = 0.5,
    blur_sigma: int = 26,
) -> str:
    """Turn any aspect ratio into the vertical frame.

    ``crop`` is the default because it fills the screen; ``blur_pad`` keeps the
    entire original frame visible (used when cropping would cut a subject in
    half) and ``contain`` is the honest letterbox.
    """
    if mode == "contain":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
        )
    if mode == "blur_pad":
        return (
            f"split=2[__bg][__fg];"
            f"[__bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},gblur=sigma={blur_sigma},eq=brightness=-0.06[__bgb];"
            f"[__fg]scale={width}:-2:force_original_aspect_ratio=decrease[__fgs];"
            f"[__bgb][__fgs]overlay=(W-w)/2:(H-h)/2,setsar=1"
        )
    return (
        f"{_focus_crop(width, height, focus_x, focus_y)},"
        f"scale={width}:{height}:flags=lanczos,setsar=1"
    )


def build_remix_chain(op: RemixOp, *, width: int = OUT_WIDTH, height: int = OUT_HEIGHT,
                      fps: int = OUT_FPS) -> str:
    """Compose the full video filter chain for one remix operation."""
    parts: List[str] = []
    if op.speed and abs(op.speed - 1.0) > 1e-3:
        parts.append(f"setpts={1.0 / op.speed:.5f}*PTS")
    if op.stabilize and capabilities().has_filter("deshake"):
        parts.append("deshake=rx=24:ry=24:edge=clamp")
    parts.append(
        build_reframe_chain(op.reframe, width=width, height=height,
                            focus_x=op.focus_x, focus_y=op.focus_y)
    )
    parts.append(f"fps={fps}")
    parts.append(color_look(op.look))
    if op.fade_in > 0:
        parts.append(f"fade=t=in:st=0:d={op.fade_in:.2f}")
    parts.append("format=yuv420p")
    return ",".join(p for p in parts if p)


def apply_remix(
    source_path: str,
    out_path: str,
    op: RemixOp,
    *,
    width: int = OUT_WIDTH,
    height: int = OUT_HEIGHT,
    fps: int = OUT_FPS,
) -> Dict[str, Any]:
    """Execute one remix operation and return what was actually produced."""
    source = Path(source_path)
    if not source.exists():
        raise FileNotFoundError(f"source clip not found: {source_path}")
    info = probe_media(str(source))
    if not info.ok or info.kind != "video":
        raise ValueError(f"not a usable video: {info.error or info.kind}")

    start = max(float(op.start or 0.0), 0.0)
    end = float(op.end) if op.end is not None else (info.duration_sec or 0.0)
    end = min(end, info.duration_sec or end)
    segment = max(end - start, 0.2)
    out_duration = segment / max(op.speed or 1.0, 0.05)
    ensure_parent(out_path)

    chain = build_remix_chain(op, width=width, height=height, fps=fps)
    if op.fade_out > 0:
        chain += f",fade=t=out:st={max(out_duration - op.fade_out, 0):.2f}:d={op.fade_out:.2f}"

    args: List[str] = ["-ss", f"{start:.3f}", "-t", f"{segment:.3f}", "-i", str(source)]
    keep_audio = (not op.mute) and info.has_audio
    if keep_audio:
        audio_chain = f"atempo={min(max(op.speed or 1.0, 0.5), 2.0):.3f},aresample=48000"
        args += ["-filter_complex", f"[0:v]{chain}[v];[0:a]{audio_chain}[a]", "-map", "[v]", "-map", "[a]"]
        args += [*INTERMEDIATE_VIDEO_ENCODE, *AUDIO_ENCODE]
    else:
        # Silence keeps every clip structurally identical for concatenation.
        args += ["-f", "lavfi", "-t", f"{out_duration:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        args += ["-filter_complex", f"[0:v]{chain}[v]", "-map", "[v]", "-map", "1:a"]
        args += [*INTERMEDIATE_VIDEO_ENCODE, *AUDIO_ENCODE]
    args += ["-t", f"{out_duration:.3f}", out_path]

    run_ffmpeg(args, label=f"remix:{op.op}", timeout=600)
    result = probe_media(out_path)
    return {
        "path": out_path,
        "op": op.op,
        "source_start": round(start, 3),
        "source_end": round(end, 3),
        "speed": op.speed,
        "reframe": op.reframe,
        "look": op.look,
        "stabilized": bool(op.stabilize and capabilities().has_filter("deshake")),
        "audio_kept": keep_audio,
        "duration_sec": result.duration_sec,
        "width": result.width,
        "height": result.height,
        "size_bytes": result.size_bytes,
    }


def extract_segment_thumbnail(source_path: str, out_path: str, at_sec: float,
                              width: int = 480) -> Optional[str]:
    """Grab a representative still so the UI can show real frames, not guesses."""
    try:
        ensure_parent(out_path)
        run_ffmpeg(
            ["-ss", f"{max(at_sec, 0):.3f}", "-i", source_path, "-frames:v", "1",
             "-vf", f"scale={width}:-2", "-update", "1", out_path],
            label="thumbnail", timeout=120,
        )
        return out_path if Path(out_path).exists() else None
    except Exception as exc:  # noqa: BLE001 - a missing thumbnail must not fail a job
        log.warning("thumbnail extraction failed for %s: %s", source_path, exc)
        return None


#: Editing-style transition names -> the FFmpeg `xfade` effect that draws them.
#:
#: `concat_clips` took a `transition` argument from the first day, recorded it
#: in its report, and joined the clips with a plain `concat` regardless. Every
#: editing style names one — soft_dissolve, whip_pan, match_cut — the timeline
#: stored it, the report printed it, and every cut in every ad was hard. It is
#: most of why a reel of stills reads as a slideshow rather than an edit.
#:
#: A match cut IS a hard cut — two shots that line up. It stays a cut here on
#: purpose; what makes it a match is the framing, not a dissolve.
XFADE_EFFECTS: Dict[str, str] = {
    "soft_dissolve": "fade",
    "dissolve": "fade",
    "fade": "fade",
    "fade_black": "fadeblack",
    "whip_pan": "slideleft",
    "whip_pan_right": "slideright",
    "wipe": "wiperight",
    "slide_up": "slideup",
    "zoom_blur": "smoothleft",
    "circle": "circleopen",
}


def xfade_effect(transition: Optional[str]) -> Optional[str]:
    """The xfade effect for a style's transition name, or None for a cut."""
    return XFADE_EFFECTS.get((transition or "").strip().lower())


def _xfade_chain(count: int, durations: Sequence[float], effect: str, overlap: float) -> List[str]:
    """Cross-fade the clips without shortening the reel.

    An overlap of `d` seconds normally eats `d` out of the running time, which
    would slide the picture off the voice-over — and the voice is what every
    caption is timed against. So each outgoing clip is padded by `d` first
    (its last frame held), and the dissolve consumes exactly that padding:
    with offsets at the cumulative un-padded durations, the finished reel is
    the same length it would have been with hard cuts, to the frame.
    """
    parts: List[str] = []
    for index in range(count - 1):
        parts.append(f"[v{index}]tpad=stop_mode=clone:stop_duration={overlap:.3f}[p{index}]")
    parts.append(f"[p0]null[x0]")

    cursor = 0.0
    for index in range(1, count):
        cursor += durations[index - 1]
        source = f"[p{index}]" if index < count - 1 else f"[v{index}]"
        out = f"[x{index}]" if index < count - 1 else "[v]"
        parts.append(
            f"[x{index - 1}]{source}xfade=transition={effect}"
            f":duration={overlap:.3f}:offset={cursor:.3f}{out}"
        )
    return parts


def concat_clips(clip_paths: Sequence[str], out_path: str, *, width: int = OUT_WIDTH,
                 height: int = OUT_HEIGHT, fps: int = OUT_FPS,
                 transition: str = "cut", transition_sec: float = 0.0) -> Dict[str, Any]:
    """Join normalised scene clips into one continuous reel.

    Uses the concat *filter* rather than the demuxer: the demuxer's stream-copy
    path silently produces broken output whenever two clips differ in any
    encoding parameter, and "silently broken" is the worst possible failure for
    a render pipeline.
    """
    clips = [c for c in clip_paths if c and Path(c).exists()]
    if not clips:
        raise ValueError("no clips to concatenate")
    ensure_parent(out_path)

    args: List[str] = []
    for clip in clips:
        args += ["-i", clip]

    graph: List[str] = []
    for index in range(len(clips)):
        graph.append(
            f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},fps={fps},setsar=1,format=yuv420p[v{index}]"
        )
        graph.append(f"[{index}:a]aresample=48000,aformat=channel_layouts=stereo[a{index}]")

    effect = xfade_effect(transition)
    overlap = round(float(transition_sec or 0.0), 3)
    if effect and overlap > 0 and len(clips) > 1:
        durations = [probe_media(clip).duration_sec or 0.0 for clip in clips]
        if all(d > overlap * 1.5 for d in durations):
            graph += _xfade_chain(len(clips), durations, effect, overlap)
            applied = transition
        else:
            # A clip barely longer than the dissolve would be more dissolve
            # than picture. Cut instead, and say which happened.
            graph.append(f"{''.join(f'[v{i}]' for i in range(len(clips)))}concat=n={len(clips)}:v=1:a=0[v]")
            applied = "cut"
    else:
        graph.append(f"{''.join(f'[v{i}]' for i in range(len(clips)))}concat=n={len(clips)}:v=1:a=0[v]")
        applied = "cut"

    graph.append(f"{''.join(f'[a{i}]' for i in range(len(clips)))}concat=n={len(clips)}:v=0:a=1[a]")

    args += ["-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[a]"]
    args += [*VIDEO_ENCODE, *AUDIO_ENCODE, out_path]
    run_ffmpeg(args, label="concat", timeout=900)

    info = probe_media(out_path)
    return {
        "path": out_path,
        "clips": len(clips),
        "duration_sec": info.duration_sec,
        "width": info.width,
        "height": info.height,
        "size_bytes": info.size_bytes,
        "transition": applied,
        "transition_requested": transition,
        "transition_sec": overlap if applied != "cut" else 0.0,
    }


# --------------------------------------------------------------------------
# Plan helpers
# --------------------------------------------------------------------------
_TIME_RE = re.compile(r"^(\d+):(\d{1,2}(?:\.\d+)?)$")


def parse_timecode(value: Any) -> Optional[float]:
    """Accept 12.5, '12.5' or '0:12.5' — ad briefs arrive in all three."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    match = _TIME_RE.match(text)
    if match:
        return int(match.group(1)) * 60 + float(match.group(2))
    try:
        return float(text)
    except ValueError:
        return None


def op_from_dict(data: Dict[str, Any]) -> RemixOp:
    return RemixOp(
        op=data.get("op", "keep"),
        start=parse_timecode(data.get("start")),
        end=parse_timecode(data.get("end")),
        speed=float(data.get("speed", 1.0) or 1.0),
        reframe=data.get("reframe", "crop") if data.get("reframe") in REFRAME_MODES else "crop",
        focus_x=float(data.get("focus_x", 0.5)),
        focus_y=float(data.get("focus_y", 0.5)),
        look=data.get("look", "neutral"),
        stabilize=bool(data.get("stabilize", False)),
        mute=bool(data.get("mute", True)),
        fade_in=float(data.get("fade_in", 0.0) or 0.0),
        fade_out=float(data.get("fade_out", 0.0) or 0.0),
        notes=data.get("notes") or {},
    )
