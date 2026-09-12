"""FFmpeg process layer.

One place that knows how to call FFmpeg, what this build can do, and what the
house encoding settings are. Everything else in app.media builds filter graphs
and hands them here.
"""
from __future__ import annotations

import functools
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

from app.core.config import settings

log = logging.getLogger("adflow.media")

#: House output format. 9:16 vertical is the product's primary deliverable.
OUT_WIDTH = 1080
OUT_HEIGHT = 1920
OUT_FPS = 30
OUT_SAMPLE_RATE = 48000
OUT_AUDIO_BITRATE = "192k"

#: Encoder settings shared by every render so concatenation never fails on a
#: parameter mismatch.
VIDEO_ENCODE: List[str] = [
    "-c:v", "libx264",
    "-preset", "veryfast",
    "-crf", "20",
    "-pix_fmt", "yuv420p",
    "-profile:v", "high",
    "-level", "4.1",
    "-movflags", "+faststart",
    "-r", str(OUT_FPS),
]
AUDIO_ENCODE: List[str] = [
    "-c:a", "aac",
    "-b:a", OUT_AUDIO_BITRATE,
    "-ar", str(OUT_SAMPLE_RATE),
    "-ac", "2",
]

#: Scene clips and other intermediates are re-encoded again during assembly,
#: so spending CPU on compression efficiency there is wasted — speed matters
#: far more than file size for a file that lives for ninety seconds.
INTERMEDIATE_VIDEO_ENCODE: List[str] = [
    "-c:v", "libx264",
    "-preset", "ultrafast",
    "-crf", "18",
    "-pix_fmt", "yuv420p",
    "-r", str(OUT_FPS),
]


class FFmpegError(RuntimeError):
    """FFmpeg exited non-zero. Carries the tail of stderr for the job record."""

    def __init__(self, message: str, stderr: str = "", cmd: Optional[Sequence[str]] = None):
        super().__init__(message)
        self.stderr = stderr[-4000:]
        self.cmd = list(cmd or [])


@dataclass(frozen=True)
class FFmpegCapabilities:
    available: bool
    version: str
    filters: frozenset
    encoders: frozenset

    def has_filter(self, name: str) -> bool:
        return name in self.filters

    def has_encoder(self, name: str) -> bool:
        return name in self.encoders


def ffmpeg_available() -> bool:
    return shutil.which(settings.FFMPEG_BIN) is not None


def ffprobe_available() -> bool:
    return shutil.which(settings.FFPROBE_BIN) is not None


@functools.lru_cache(maxsize=1)
def capabilities() -> FFmpegCapabilities:
    """Inspect the FFmpeg build once. Never assume a filter exists."""
    if not ffmpeg_available():
        return FFmpegCapabilities(False, "", frozenset(), frozenset())
    try:
        version = subprocess.run(
            [settings.FFMPEG_BIN, "-version"], capture_output=True, text=True, timeout=20
        ).stdout.splitlines()[0]
        raw_filters = subprocess.run(
            [settings.FFMPEG_BIN, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=30
        ).stdout
        raw_encoders = subprocess.run(
            [settings.FFMPEG_BIN, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=30
        ).stdout
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("ffmpeg capability probe failed: %s", exc)
        return FFmpegCapabilities(False, "", frozenset(), frozenset())

    filters = {
        parts[1]
        for line in raw_filters.splitlines()
        if len(parts := line.split()) >= 2 and not line.startswith("Filters:")
    }
    encoders = {
        parts[1]
        for line in raw_encoders.splitlines()
        if len(parts := line.split()) >= 2 and not line.startswith("Encoders:")
    }
    return FFmpegCapabilities(True, version, frozenset(filters), frozenset(encoders))


def render_enabled() -> bool:
    """Local rendering is a deliberate switch — a hosted worker may disable it."""
    return bool(settings.ENABLE_LOCAL_RENDER) and ffmpeg_available()


def run_ffmpeg(args: Sequence[str], *, timeout: int = 600, label: str = "ffmpeg") -> str:
    """Run FFmpeg with the given arguments. Returns stderr (FFmpeg's log stream)."""
    cmd = [settings.FFMPEG_BIN, "-hide_banner", "-nostdin", "-y", *args]
    log.debug("%s: %s", label, " ".join(cmd))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - timing dependent
        raise FFmpegError(f"{label} timed out after {timeout}s", "", cmd) from exc
    if proc.returncode != 0:
        raise FFmpegError(f"{label} failed (exit {proc.returncode})", proc.stderr or "", cmd)
    return proc.stderr or ""


def ensure_parent(path: str) -> str:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path


def escape_filter_path(path: str) -> str:
    """Escape a filesystem path for use inside a filtergraph option value."""
    return path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'").replace(",", "\\,")


def fit_cover(width: int = OUT_WIDTH, height: int = OUT_HEIGHT) -> str:
    """Scale-and-crop so any source fills the vertical frame with no bars."""
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1"
    )


def fit_contain(width: int = OUT_WIDTH, height: int = OUT_HEIGHT, pad_color: str = "black") -> str:
    """Scale to fit inside the frame, padding the remainder (blur-free variant)."""
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={pad_color},setsar=1"
    )


def fit_blur_pad(width: int = OUT_WIDTH, height: int = OUT_HEIGHT, blur: int = 28) -> str:
    """Blurred-background reframe — keeps the whole subject and fills the frame.

    Used when a landscape clip must go vertical and cropping would decapitate
    the subject. Returns a *complex* graph fragment expecting one input labelled
    [in] and producing [out].
    """
    return (
        f"[in]split=2[bg][fg];"
        f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},gblur=sigma={blur}[bgb];"
        f"[fg]scale={width}:-2:force_original_aspect_ratio=decrease[fgs];"
        f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1[out]"
    )


COLOR_LOOKS = {
    # name -> eq/curve filter chain. Deliberately gentle: real project
    # photography must not be destroyed by a "look".
    "neutral": "eq=contrast=1.0:brightness=0.0:saturation=1.0",
    "neutral_bright": "eq=contrast=1.04:brightness=0.02:saturation=1.02",
    "warm_film": "eq=contrast=1.06:brightness=0.01:saturation=1.06,colorbalance=rs=0.04:gs=0.01:bs=-0.04",
    "cool_contrast": "eq=contrast=1.10:brightness=0.0:saturation=0.98,colorbalance=rs=-0.03:bs=0.05",
    "punchy": "eq=contrast=1.14:brightness=0.01:saturation=1.16",
    "muted_elegant": "eq=contrast=1.02:brightness=0.01:saturation=0.90",
}


def color_look(name: str) -> str:
    return COLOR_LOOKS.get(name, COLOR_LOOKS["neutral"])
