"""Photo Motion — turn a still into a cinematic vertical clip.

This is the economic heart of AdFlow AI. A real-estate customer usually
already owns good photography; animating it costs a fraction of a cent of CPU
instead of dollars of AI video, and for most scenes it looks better because the
building is genuinely theirs.

Movement is deliberately restrained: slow, eased, never more than ~12% travel.
Aggressive motion is what makes cheap slideshow ads look cheap.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.media.ffmpeg import (
    AUDIO_ENCODE,
    INTERMEDIATE_VIDEO_ENCODE,
    OUT_FPS,
    OUT_HEIGHT,
    OUT_WIDTH,
    VIDEO_ENCODE,
    color_look,
    ensure_parent,
    run_ffmpeg,
)

log = logging.getLogger("adflow.media.motion")


@dataclass(frozen=True)
class MotionPreset:
    key: str
    label_en: str
    label_ar: str
    zoom_from: float
    zoom_to: float
    pan_x: float  # fraction of the spare width travelled, -1..1
    pan_y: float
    description_ar: str


#: The movement vocabulary exposed to the Director and the storyboard.
MOTION_PRESETS: Dict[str, MotionPreset] = {
    p.key: p
    for p in (
        MotionPreset("push_in", "Push In", "تقريب هادئ", 1.00, 1.12, 0.0, 0.0,
                     "تقريب بطيء يشد النظر للمشروع"),
        MotionPreset("pull_out", "Pull Out", "إبعاد هادئ", 1.12, 1.00, 0.0, 0.0,
                     "إبعاد يكشف المشهد كامل"),
        MotionPreset("pan_left", "Pan Left", "تحريك لليسار", 1.08, 1.08, -1.0, 0.0,
                     "مسح أفقي يمشي بالمشهد"),
        MotionPreset("pan_right", "Pan Right", "تحريك لليمين", 1.08, 1.08, 1.0, 0.0,
                     "مسح أفقي بالاتجاه الثاني"),
        MotionPreset("tilt_up", "Tilt Up", "رفع للأعلى", 1.08, 1.08, 0.0, -1.0,
                     "رفع الكاميرا يظهر الارتفاع"),
        MotionPreset("controlled_zoom", "Controlled Zoom", "تقريب محسوب", 1.00, 1.06, 0.0, 0.0,
                     "حركة خفيفة جداً للمشاهد المعلوماتية"),
        MotionPreset("ken_burns", "Ken Burns", "كين بيرنز", 1.02, 1.14, 0.6, -0.5,
                     "تقريب مع انزياح قطري، إحساس سينمائي"),
        MotionPreset("parallax", "Parallax", "بارالاكس", 1.04, 1.12, 0.35, 0.0,
                     "عمق بطبقتين: خلفية ثابتة وواجهة تتحرك"),
        MotionPreset("static", "Static", "ثابت", 1.0, 1.0, 0.0, 0.0,
                     "بدون حركة — للنصوص والعروض"),
    )
}

#: Order the Director walks when it wants variety across consecutive scenes.
MOTION_ROTATION: List[str] = ["push_in", "pan_right", "ken_burns", "pull_out", "pan_left", "tilt_up"]


def preset_for(name: Optional[str]) -> MotionPreset:
    return MOTION_PRESETS.get((name or "").strip().lower(), MOTION_PRESETS["push_in"])


def recommend_motion(
    *,
    index: int,
    orientation: str = "landscape",
    is_hook: bool = False,
    purpose: str = "",
    motion_potential: float = 0.6,
) -> str:
    """Pick a movement that suits the photo and its place in the story."""
    if "offer" in purpose or "معلوم" in purpose or "سعر" in purpose:
        return "controlled_zoom"
    if is_hook:
        return "push_in"
    if orientation == "portrait":
        # A tall frame has little spare width — vertical travel reads better.
        return "tilt_up" if motion_potential > 0.5 else "controlled_zoom"
    if motion_potential < 0.35:
        return "controlled_zoom"
    return MOTION_ROTATION[index % len(MOTION_ROTATION)]


def _ease_expression(from_value: float, to_value: float, frames: int) -> str:
    """Smoothstep between two values over ``frames`` output frames.

    Linear zoom looks mechanical; smoothstep gives the slow-in/slow-out a real
    camera operator produces.
    """
    if abs(to_value - from_value) < 1e-6 or frames <= 1:
        return f"{from_value:.5f}"
    t = f"(on/{frames - 1})"
    smooth = f"({t}*{t}*(3-2*{t}))"
    return f"({from_value:.5f}+({to_value - from_value:.5f})*{smooth})"


def build_motion_filter(
    preset: MotionPreset,
    *,
    duration_sec: float,
    width: int = OUT_WIDTH,
    height: int = OUT_HEIGHT,
    fps: int = OUT_FPS,
    look: str = "neutral",
    supersample: Optional[float] = None,
) -> str:
    """Filter chain: still image -> moving vertical clip.

    The still is fitted to a canvas slightly larger than the output so zoompan
    crops from real pixels instead of magnifying an already-final frame (which
    is what produces the classic zoompan shimmer). "Slightly larger" is derived
    from the preset's own maximum zoom — scaling further just burns CPU and
    softens the image.
    """
    frames = max(int(round(duration_sec * fps)), 2)
    if supersample is None:
        supersample = max(preset.zoom_from, preset.zoom_to, 1.0) * 1.06
    big_w = int(width * supersample) // 2 * 2
    big_h = int(height * supersample) // 2 * 2
    zoom = _ease_expression(preset.zoom_from, preset.zoom_to, frames)

    # zoompan's x/y are top-left of the crop window inside the (already scaled)
    # frame. Centre it, then travel by the requested fraction of the slack.
    centre_x = "iw/2-(iw/zoom/2)"
    centre_y = "ih/2-(ih/zoom/2)"
    if abs(preset.pan_x) > 1e-6:
        travel = f"(iw-iw/zoom)/2*{preset.pan_x:.3f}"
        progress = f"(on/{frames - 1})"
        x_expr = f"{centre_x}+{travel}*({progress}*{progress}*(3-2*{progress})*2-1)"
    else:
        x_expr = centre_x
    if abs(preset.pan_y) > 1e-6:
        travel_y = f"(ih-ih/zoom)/2*{preset.pan_y:.3f}"
        progress = f"(on/{frames - 1})"
        y_expr = f"{centre_y}+{travel_y}*({progress}*{progress}*(3-2*{progress})*2-1)"
    else:
        y_expr = centre_y

    chain = (
        f"scale={big_w}:{big_h}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={big_w}:{big_h},"
        f"zoompan=z='{zoom}':x='{x_expr}':y='{y_expr}':d=1:s={width}x{height}:fps={fps},"
        f"{color_look(look)},"
        f"format=yuv420p,setsar=1"
    )
    return chain


def render_photo_motion(
    image_path: str,
    out_path: str,
    *,
    duration_sec: float = 3.5,
    motion: str = "push_in",
    look: str = "neutral",
    width: int = OUT_WIDTH,
    height: int = OUT_HEIGHT,
    fps: int = OUT_FPS,
    fade_in: float = 0.0,
    fade_out: float = 0.0,
    silent_audio: bool = True,
) -> Dict[str, Any]:
    """Render a still image into a real MP4 scene clip."""
    source = Path(image_path)
    if not source.exists():
        raise FileNotFoundError(f"photo not found: {image_path}")
    duration_sec = max(float(duration_sec), 0.5)
    preset = preset_for(motion)
    ensure_parent(out_path)

    chain = build_motion_filter(
        preset, duration_sec=duration_sec, width=width, height=height, fps=fps, look=look
    )
    if fade_in > 0:
        chain += f",fade=t=in:st=0:d={fade_in:.2f}"
    if fade_out > 0:
        chain += f",fade=t=out:st={max(duration_sec - fade_out, 0):.2f}:d={fade_out:.2f}"

    # -framerate must match the output rate: zoompan emits one frame per input
    # frame, so a 25fps still source would yield a clip 5/6 of the asked length.
    args: List[str] = [
        "-loop", "1", "-framerate", str(fps), "-t", f"{duration_sec:.3f}", "-i", str(source),
    ]
    if silent_audio:
        # Every scene clip carries an audio track so concatenation never has to
        # reconcile "some clips have sound, some do not".
        args += ["-f", "lavfi", "-t", f"{duration_sec:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
    args += ["-vf", chain, "-t", f"{duration_sec:.3f}", *INTERMEDIATE_VIDEO_ENCODE]
    args += [*AUDIO_ENCODE] if silent_audio else ["-an"]
    args += [out_path]

    run_ffmpeg(args, label=f"photo_motion:{preset.key}", timeout=300)
    return {
        "path": out_path,
        "motion": preset.key,
        "motion_label_ar": preset.label_ar,
        "duration_sec": round(duration_sec, 3),
        "width": width,
        "height": height,
        "fps": fps,
        "look": look,
        "size_bytes": Path(out_path).stat().st_size,
    }


def sequence_motions(count: int, *, seed_index: int = 0) -> List[str]:
    """Vary movement across a photo sequence so it never feels like a slideshow."""
    if count <= 0:
        return []
    step = max(1, int(math.gcd(len(MOTION_ROTATION), max(count, 1)) == 1) or 1)
    return [MOTION_ROTATION[(seed_index + i * step) % len(MOTION_ROTATION)] for i in range(count)]
