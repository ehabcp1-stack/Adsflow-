"""Real media metadata via FFprobe.

The browser's idea of a file is not trustworthy — orientation, duration and
audio presence all decide how a scene is produced, so they are read from the
file itself.
"""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.config import settings
from app.media.ffmpeg import ffprobe_available

log = logging.getLogger("adflow.media.probe")

IMAGE_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}
VIDEO_MIME = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".m4v": "video/x-m4v",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
}
AUDIO_MIME = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav", ".aac": "audio/aac"}

ACCEPTED_EXTENSIONS = set(IMAGE_MIME) | set(VIDEO_MIME) | set(AUDIO_MIME)


@dataclass
class MediaInfo:
    ok: bool = False
    kind: str = "unknown"  # image | video | audio | unknown
    width: Optional[int] = None
    height: Optional[int] = None
    duration_sec: Optional[float] = None
    fps: Optional[float] = None
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    has_audio: bool = False
    audio_channels: Optional[int] = None
    sample_rate: Optional[int] = None
    bitrate: Optional[int] = None
    rotation: int = 0
    orientation: str = "landscape"
    size_bytes: int = 0
    error: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def aspect_ratio(self) -> Optional[float]:
        if self.width and self.height:
            return round(self.width / self.height, 4)
        return None

    @property
    def is_vertical(self) -> bool:
        return self.orientation == "portrait"

    def as_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("raw", None)
        data["aspect_ratio"] = self.aspect_ratio
        return data


def _orientation(width: Optional[int], height: Optional[int]) -> str:
    if not width or not height:
        return "unknown"
    if abs(width - height) / max(width, height) < 0.05:
        return "square"
    return "portrait" if height > width else "landscape"


def _float(value: Any) -> Optional[float]:
    try:
        result = float(value)
        return result if result == result else None  # filter NaN
    except (TypeError, ValueError):
        return None


def _parse_fps(rate: Optional[str]) -> Optional[float]:
    if not rate or "/" not in rate:
        return _float(rate)
    num, _, den = rate.partition("/")
    n, d = _float(num), _float(den)
    if not n or not d:
        return None
    return round(n / d, 3)


def probe_media(path: str) -> MediaInfo:
    """Read real metadata from a file on disk."""
    file_path = Path(path)
    info = MediaInfo()
    if not file_path.exists():
        info.error = "file not found"
        return info
    info.size_bytes = file_path.stat().st_size
    if info.size_bytes == 0:
        info.error = "file is empty"
        return info

    suffix = file_path.suffix.lower()
    if suffix == ".svg":
        # Vector placeholder frames — FFprobe cannot read them, and they are
        # ours, so they are described directly.
        info.ok, info.kind, info.width, info.height = True, "image", 1080, 1920
        info.orientation = "portrait"
        return info

    if not ffprobe_available():
        info.error = "ffprobe unavailable"
        info.kind = "image" if suffix in IMAGE_MIME else "video" if suffix in VIDEO_MIME else "unknown"
        return info

    cmd = [
        settings.FFPROBE_BIN, "-v", "error",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(file_path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:  # pragma: no cover - timing dependent
        info.error = "ffprobe timed out"
        return info
    if proc.returncode != 0:
        info.error = (proc.stderr or "ffprobe failed").strip()[:300]
        return info
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        info.error = "ffprobe returned invalid JSON"
        return info

    info.raw = data
    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if not streams:
        info.error = "no decodable streams (file may be corrupt)"
        return info

    info.bitrate = int(_float(fmt.get("bit_rate")) or 0) or None
    info.duration_sec = _float(fmt.get("duration"))

    if audio:
        info.has_audio = True
        info.audio_codec = audio.get("codec_name")
        info.audio_channels = int(_float(audio.get("channels")) or 0) or None
        info.sample_rate = int(_float(audio.get("sample_rate")) or 0) or None

    if video:
        info.width = int(_float(video.get("width")) or 0) or None
        info.height = int(_float(video.get("height")) or 0) or None
        info.video_codec = video.get("codec_name")
        info.fps = _parse_fps(video.get("avg_frame_rate")) or _parse_fps(video.get("r_frame_rate"))
        if info.duration_sec is None:
            info.duration_sec = _float(video.get("duration"))
        for side in video.get("side_data_list") or []:
            if "rotation" in side:
                info.rotation = int(_float(side.get("rotation")) or 0)
        # A phone clip stores rotation as metadata; the usable frame is swapped.
        if abs(info.rotation) in (90, 270) and info.width and info.height:
            info.width, info.height = info.height, info.width
        # Still images decode as one video frame with no real duration.
        still = (video.get("codec_name") in {"mjpeg", "png", "webp", "bmp", "gif"}) and (
            not info.duration_sec or info.duration_sec < 0.1
        )
        info.kind = "image" if still or suffix in IMAGE_MIME and not info.has_audio and (
            not info.duration_sec or info.duration_sec < 0.5
        ) else "video"
    elif audio:
        info.kind = "audio"
    else:
        info.kind = "unknown"

    if info.kind == "image":
        info.duration_sec = None

    info.orientation = _orientation(info.width, info.height)
    info.ok = bool(info.width or info.kind == "audio")
    if not info.ok:
        info.error = info.error or "no usable video or audio stream"
    return info


def guess_mime(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return IMAGE_MIME.get(suffix) or VIDEO_MIME.get(suffix) or AUDIO_MIME.get(suffix) or "application/octet-stream"


def kind_for_extension(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in IMAGE_MIME:
        return "image"
    if suffix in VIDEO_MIME:
        return "video"
    if suffix in AUDIO_MIME:
        return "audio"
    return "unknown"
