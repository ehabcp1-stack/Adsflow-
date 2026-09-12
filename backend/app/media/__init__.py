"""AdFlow AI real media engine.

Everything in this package touches actual pixels and actual audio through
FFmpeg/FFprobe and Pillow. Nothing here calls a paid API — it is the layer
that lets AdFlow AI produce a genuine 1080x1920 MP4 from material the
customer already owns, which is the whole economic argument of the product.

Modules
-------
ffmpeg     process runner, capability probe, shared encoder settings
probe      ffprobe metadata + corruption detection
motion     photo -> motion clip (push in / pan / Ken Burns ...)
remix      real operations on uploaded footage (trim, reframe, speed, grade)
captions   Arabic caption rasterisation (RTL shaping done by us, never by a model)
overlays   logo / CTA / end screen / lower thirds
audio      voice + music + SFX mixing, ducking, mastering
shots      shot boundary detection and per-segment scoring
assemble   timeline -> final reel
"""
from __future__ import annotations

from app.media.ffmpeg import FFmpegError, ffmpeg_available, ffprobe_available, run_ffmpeg
from app.media.probe import MediaInfo, probe_media

__all__ = [
    "FFmpegError",
    "MediaInfo",
    "ffmpeg_available",
    "ffprobe_available",
    "probe_media",
    "run_ffmpeg",
]
