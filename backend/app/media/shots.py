"""Shot detection and per-segment scoring for uploaded footage.

Before AdFlow AI can propose "keep these four shots, drop the rest", it has to
know what shots exist. FFmpeg's scene-change score does the boundary work;
Pillow measures each resulting segment so the plan can be argued for rather
than asserted — exposure, contrast, detail and how much the frame moves.
"""
from __future__ import annotations

import logging
import math
import re
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageFilter, ImageStat

from app.media.ffmpeg import ensure_parent, run_ffmpeg
from app.media.probe import probe_media

log = logging.getLogger("adflow.media.shots")

_PTS_RE = re.compile(r"pts_time:([0-9.]+)")

#: Below this a "shot" is a flash frame, not usable material.
MIN_SHOT_SEC = 1.0
MAX_SHOT_SEC = 8.0


@dataclass
class Segment:
    index: int = 0
    start: float = 0.0
    end: float = 0.0
    duration: float = 0.0
    thumbnail: Optional[str] = None
    brightness: float = 0.0
    contrast: float = 0.0
    sharpness: float = 0.0
    colorfulness: float = 0.0
    motion: float = 0.0
    quality: float = 0.0
    hook_potential: float = 0.0
    project_visibility: float = 0.0
    orientation: str = "landscape"
    audio_important: bool = False
    strength: str = "usable"  # strong | usable | weak
    recommendation: str = "keep"  # keep | trim | drop
    reason_ar: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def detect_scene_cuts(path: str, *, threshold: float = 0.30, timeout: int = 600) -> List[float]:
    """Return scene-change timestamps in seconds."""
    try:
        # showinfo writes to FFmpeg's log (stderr), which run_ffmpeg returns.
        # `metadata=print:file=-` would go to stdout and be lost here.
        stderr = run_ffmpeg(
            ["-i", path, "-vf", f"select='gt(scene,{threshold})',showinfo",
             "-an", "-f", "null", "-"],
            label="shots:detect", timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 - detection must never fail a job
        log.warning("scene detection failed for %s: %s", path, exc)
        return []
    return sorted({round(float(m), 3) for m in _PTS_RE.findall(stderr)})


def split_into_segments(duration: float, cuts: Sequence[float], *,
                        min_sec: float = MIN_SHOT_SEC,
                        max_sec: float = MAX_SHOT_SEC) -> List[Tuple[float, float]]:
    """Turn cut points into usable segments, merging flashes and splitting longs."""
    points = [0.0] + [c for c in cuts if 0.0 < c < duration] + [float(duration)]
    raw: List[Tuple[float, float]] = []
    carry: Optional[float] = None  # start of a flash waiting to be merged forward
    for start, end in zip(points, points[1:]):
        if end - start <= 0:
            continue
        if carry is not None:
            start, carry = carry, None
        if end - start < min_sec:
            if raw:
                raw[-1] = (raw[-1][0], end)  # absorb into the previous shot
            else:
                carry = start  # nothing behind it yet — merge into the next one
            continue
        raw.append((start, end))
    if carry is not None and raw:
        raw[0] = (carry, raw[0][1])
    elif carry is not None:
        raw.append((carry, float(duration)))

    segments: List[Tuple[float, float]] = []
    for start, end in raw:
        span = end - start
        if span <= max_sec:
            segments.append((start, end))
            continue
        chunks = max(int(math.ceil(span / max_sec)), 1)
        step = span / chunks
        for i in range(chunks):
            segments.append((round(start + i * step, 3), round(start + (i + 1) * step, 3)))
    return [(round(s, 3), round(e, 3)) for s, e in segments if e - s >= 0.4]


def _frame_metrics(image: Image.Image) -> Dict[str, float]:
    grey = image.convert("L")
    stat = ImageStat.Stat(grey)
    brightness = stat.mean[0] / 255.0
    contrast = min(stat.stddev[0] / 80.0, 1.0)
    edges = ImageStat.Stat(grey.filter(ImageFilter.FIND_EDGES))
    sharpness = min(edges.stddev[0] / 55.0, 1.0)
    rgb = ImageStat.Stat(image.convert("RGB"))
    spread = max(rgb.mean) - min(rgb.mean)
    colorfulness = min(spread / 90.0, 1.0)
    return {
        "brightness": round(brightness, 3),
        "contrast": round(contrast, 3),
        "sharpness": round(sharpness, 3),
        "colorfulness": round(colorfulness, 3),
    }


def _difference(a: Image.Image, b: Image.Image) -> float:
    small_a = a.convert("L").resize((64, 64))
    small_b = b.convert("L").resize((64, 64))
    pixels_a, pixels_b = list(small_a.tobytes()), list(small_b.tobytes())
    total = sum(abs(x - y) for x, y in zip(pixels_a, pixels_b))
    return min(total / (64 * 64 * 255.0) * 6.0, 1.0)


def _grab_frames(path: str, at: Sequence[float], out_dir: str, width: int = 320) -> List[str]:
    frames: List[str] = []
    for index, moment in enumerate(at):
        out = str(Path(out_dir) / f"probe_{index:03d}.jpg")
        try:
            ensure_parent(out)
            run_ffmpeg(
                ["-ss", f"{max(moment, 0):.3f}", "-i", path, "-frames:v", "1",
                 "-vf", f"scale={width}:-2", "-q:v", "4", "-update", "1", out],
                label="shots:frame", timeout=120,
            )
            if Path(out).exists():
                frames.append(out)
        except Exception as exc:  # noqa: BLE001
            log.debug("frame grab failed at %.2fs: %s", moment, exc)
    return frames


def _exposure_penalty(brightness: float) -> float:
    """A well-exposed frame sits near the middle; punish crush and blow-out."""
    return max(0.0, 1.0 - abs(brightness - 0.52) * 2.6)


def analyze_segment(path: str, start: float, end: float, index: int, *,
                    thumb_dir: str, orientation: str = "landscape") -> Segment:
    duration = max(end - start, 0.1)
    segment = Segment(index=index, start=round(start, 3), end=round(end, 3),
                      duration=round(duration, 3), orientation=orientation)

    with tempfile.TemporaryDirectory() as tmp:
        moments = [start + duration * f for f in (0.15, 0.5, 0.85)]
        frames = _grab_frames(path, moments, tmp)
        if not frames:
            segment.strength, segment.recommendation = "weak", "drop"
            segment.reason_ar = "ما كدرنا نقرأ هذا المقطع"
            return segment
        images = [Image.open(f).convert("RGB") for f in frames]
        metrics = [_frame_metrics(im) for im in images]
        segment.brightness = round(sum(m["brightness"] for m in metrics) / len(metrics), 3)
        segment.contrast = round(sum(m["contrast"] for m in metrics) / len(metrics), 3)
        segment.sharpness = round(sum(m["sharpness"] for m in metrics) / len(metrics), 3)
        segment.colorfulness = round(sum(m["colorfulness"] for m in metrics) / len(metrics), 3)
        segment.motion = round(_difference(images[0], images[-1]), 3) if len(images) > 1 else 0.0

        thumb = Path(thumb_dir) / f"segment_{index:03d}.jpg"
        ensure_parent(str(thumb))
        images[len(images) // 2].resize(
            (480, max(int(480 * images[0].height / max(images[0].width, 1)), 1))
        ).save(thumb, "JPEG", quality=82)
        segment.thumbnail = str(thumb)

    quality = (
        0.34 * segment.sharpness
        + 0.26 * segment.contrast
        + 0.22 * _exposure_penalty(segment.brightness)
        + 0.18 * segment.colorfulness
    )
    segment.quality = round(min(max(quality, 0.0), 1.0), 3)
    # A hook needs to be sharp, bright and alive — a static dark shot never is.
    segment.hook_potential = round(
        min(0.55 * segment.quality + 0.30 * segment.motion + 0.15 * _exposure_penalty(segment.brightness), 1.0), 3
    )
    segment.project_visibility = round(min(0.6 * segment.sharpness + 0.4 * segment.contrast, 1.0), 3)

    if segment.quality >= 0.62 and segment.duration >= 1.2:
        segment.strength, segment.recommendation = "strong", "keep"
        segment.reason_ar = "لقطة واضحة وقوية — تصلح للريل"
    elif segment.quality >= 0.42:
        segment.strength, segment.recommendation = "usable", "trim"
        segment.reason_ar = "لقطة مقبولة — نقصّها ونستعملها بالوسط"
    else:
        segment.strength, segment.recommendation = "weak", "drop"
        segment.reason_ar = "جودة ضعيفة أو إضاءة مو مضبوطة — الأفضل نستبعدها"
    return segment


def analyze_video(path: str, *, thumb_dir: Optional[str] = None,
                  threshold: float = 0.30, max_segments: int = 24) -> Dict[str, Any]:
    """Full shot analysis of an uploaded video."""
    info = probe_media(path)
    if not info.ok or info.kind != "video":
        return {"ok": False, "error": info.error or "not a video", "segments": []}

    duration = info.duration_sec or 0.0
    cuts = detect_scene_cuts(path, threshold=threshold)
    spans = split_into_segments(duration, cuts)[:max_segments]
    if not spans:
        spans = [(0.0, min(duration, MAX_SHOT_SEC))]

    thumbs = thumb_dir or tempfile.mkdtemp(prefix="adflow-shots-")
    Path(thumbs).mkdir(parents=True, exist_ok=True)
    segments = [
        analyze_segment(path, start, end, index, thumb_dir=thumbs, orientation=info.orientation)
        for index, (start, end) in enumerate(spans)
    ]
    keepers = [s for s in segments if s.recommendation != "drop"]
    best = max(segments, key=lambda s: s.hook_potential, default=None)

    return {
        "ok": True,
        "duration_sec": duration,
        "orientation": info.orientation,
        "has_audio": info.has_audio,
        "cuts": cuts,
        "segment_count": len(segments),
        "usable_count": len(keepers),
        "usable_duration_sec": round(sum(s.duration for s in keepers), 2),
        "retain_ratio": round(sum(s.duration for s in keepers) / duration, 3) if duration else 0.0,
        "best_opening_index": best.index if best else None,
        "segments": [s.as_dict() for s in segments],
        "thumbnail_dir": thumbs,
    }
