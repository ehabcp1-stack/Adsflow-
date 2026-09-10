"""Deterministic visual placeholders for Mock Providers.

Mock output must be *visually testable*, not an empty string. We render real
SVG frames (browsers shape Arabic correctly) and, when FFmpeg is available,
real short MP4 clips so the editing/QC/export screens have playable media.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

from app.core.config import settings
from app.services.storage import get_storage

PALETTES: List[Tuple[str, str, str]] = [
    ("#0F172A", "#1E3A8A", "#60A5FA"),
    ("#1C1917", "#7C2D12", "#FBBF24"),
    ("#0B1220", "#0E7490", "#67E8F9"),
    ("#111827", "#4C1D95", "#C4B5FD"),
    ("#0A0A0A", "#166534", "#86EFAC"),
    ("#1A120B", "#92400E", "#FCD34D"),
]


def _palette(seed: str) -> Tuple[str, str, str]:
    idx = int(hashlib.md5(seed.encode()).hexdigest(), 16) % len(PALETTES)
    return PALETTES[idx]


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _wrap(text: str, max_chars: int, max_lines: int = 2) -> List[str]:
    """Naive word wrap so long Arabic titles stay inside the frame."""
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
        if len(lines) == max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines or [text[:max_chars]]


def build_frame_svg(
    *,
    seed: str,
    title_ar: str = "",
    subtitle: str = "",
    badge: str = "",
    width: int = 1080,
    height: int = 1920,
) -> str:
    dark, mid, accent = _palette(seed)
    title_lines = _wrap(_escape(title_ar), max_chars=20, max_lines=2)
    title_font = 72 if len(title_lines) == 1 and len(title_lines[0]) <= 14 else 56
    subtitle = _escape(subtitle)[:44]
    badge = _escape(badge)[:22]
    title_svg = "".join(
        f'<tspan x="{int(width * 0.5)}" dy="{0 if index == 0 else int(title_font * 1.25)}">{line}</tspan>'
        for index, line in enumerate(title_lines)
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="0.6" y2="1">
      <stop offset="0%" stop-color="{dark}"/>
      <stop offset="55%" stop-color="{mid}"/>
      <stop offset="100%" stop-color="{dark}"/>
    </linearGradient>
    <radialGradient id="r" cx="50%" cy="32%" r="60%">
      <stop offset="0%" stop-color="{accent}" stop-opacity="0.42"/>
      <stop offset="100%" stop-color="{accent}" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="{width}" height="{height}" fill="url(#g)"/>
  <rect width="{width}" height="{height}" fill="url(#r)"/>
  <g opacity="0.20" stroke="{accent}" stroke-width="2" fill="none">
    <path d="M0 {int(height*0.62)} L{int(width*0.34)} {int(height*0.44)} L{int(width*0.62)} {int(height*0.58)} L{width} {int(height*0.40)}"/>
    <circle cx="{int(width*0.5)}" cy="{int(height*0.34)}" r="{int(width*0.30)}"/>
    <circle cx="{int(width*0.5)}" cy="{int(height*0.34)}" r="{int(width*0.20)}"/>
  </g>
  <rect x="{int(width*0.08)}" y="{int(height*0.055)}" rx="22" width="{max(int(width*0.06)+len(badge)*20, 160)}" height="66" fill="#000000" opacity="0.35"/>
  <text x="{int(width*0.10)}" y="{int(height*0.055)+45}" font-family="Inter, Helvetica, Arial, sans-serif" font-size="28" fill="{accent}" letter-spacing="2">{badge}</text>
  <text x="{int(width*0.5)}" y="{int(height*0.66)}" text-anchor="middle" direction="rtl"
        font-family="Cairo, Tahoma, 'Segoe UI', sans-serif" font-size="{title_font}" font-weight="700" fill="#FFFFFF">{title_svg}</text>
  <text x="{int(width*0.5)}" y="{int(height*0.66)+int(title_font*1.25)*len(title_lines)+28}" text-anchor="middle"
        font-family="Inter, Helvetica, Arial, sans-serif" font-size="32" fill="#E2E8F0" opacity="0.85">{subtitle}</text>
  <text x="{int(width*0.5)}" y="{height-70}" text-anchor="middle"
        font-family="Inter, Helvetica, Arial, sans-serif" font-size="26" fill="#FFFFFF" opacity="0.55">AdFlow AI · by TADAFQ</text>
</svg>"""


def save_frame(
    key: str,
    *,
    seed: str,
    title_ar: str = "",
    subtitle: str = "",
    badge: str = "",
    width: int = 1080,
    height: int = 1920,
) -> str:
    svg = build_frame_svg(
        seed=seed, title_ar=title_ar, subtitle=subtitle, badge=badge, width=width, height=height
    )
    return get_storage().put_bytes(key, svg.encode("utf-8"), "image/svg+xml")


def ffmpeg_available() -> bool:
    return shutil.which(settings.FFMPEG_BIN) is not None


def save_clip(
    key: str,
    *,
    seed: str,
    duration_sec: float = 4.0,
    label: str = "",
    width: int = 1080,
    height: int = 1920,
) -> Optional[str]:
    """Render a short branded MP4 with FFmpeg. Returns None when unavailable."""
    if not (settings.ENABLE_LOCAL_RENDER and ffmpeg_available()):
        return None
    dark, mid, accent = _palette(seed)
    storage = get_storage()
    out_path = storage.local_path(key)
    tmp_dir: Optional[str] = None
    if out_path is None:
        tmp_dir = tempfile.mkdtemp()
        out_path = str(Path(tmp_dir) / "clip.mp4")
    safe_label = label.replace(":", "\\:").replace("'", "")[:40]
    cmd = [
        settings.FFMPEG_BIN,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={mid.replace('#','0x')}:s={width}x{height}:d={max(duration_sec,1):.2f}:r=30",
        "-f",
        "lavfi",
        "-i",
        f"color=c={dark.replace('#','0x')}:s={width}x{height}:d={max(duration_sec,1):.2f}:r=30",
        "-filter_complex",
        (
            "[0:v]format=yuv420p,zoompan=z='min(zoom+0.0012,1.18)':d=1:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}[bg];"
            f"[bg]drawbox=x=0:y=ih*0.62:w=iw:h=ih*0.38:color=black@0.35:t=fill,"
            f"drawtext=text='{safe_label}':fontcolor=white:fontsize=54:x=(w-text_w)/2:y=h*0.72,"
            f"drawtext=text='AdFlow AI by TADAFQ':fontcolor={accent.replace('#','0x')}@0.9:"
            "fontsize=34:x=(w-text_w)/2:y=h-120[v]"
        ),
        "-map",
        "[v]",
        "-t",
        f"{max(duration_sec, 1):.2f}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "28",
        "-pix_fmt",
        "yuv420p",
        out_path,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=180)
    except Exception:
        # Fall back to a simpler filter chain (older ffmpeg / missing fonts).
        simple = [
            settings.FFMPEG_BIN,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={mid.replace('#','0x')}:s={width}x{height}:d={max(duration_sec,1):.2f}:r=30",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "30",
            "-pix_fmt",
            "yuv420p",
            out_path,
        ]
        try:
            subprocess.run(simple, check=True, capture_output=True, timeout=120)
        except Exception:
            return None
    if tmp_dir:
        return storage.put_file(key, out_path, "video/mp4")
    return storage.url_for(key)


def concat_clips(key: str, clip_paths: List[str], audio_path: Optional[str] = None) -> Optional[str]:
    """Assemble scene clips into one reel (local FFmpeg path)."""
    if not (settings.ENABLE_LOCAL_RENDER and ffmpeg_available()) or not clip_paths:
        return None
    storage = get_storage()
    out_path = storage.local_path(key)
    if out_path is None:  # pragma: no cover - S3 dev path
        out_path = str(Path(tempfile.mkdtemp()) / "reel.mp4")
    list_file = Path(tempfile.mkdtemp()) / "list.txt"
    list_file.write_text("".join(f"file '{p}'\n" for p in clip_paths), encoding="utf-8")
    cmd = [settings.FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file)]
    if audio_path and Path(audio_path).exists():
        cmd += ["-i", audio_path, "-c:v", "copy", "-c:a", "aac", "-shortest"]
    else:
        cmd += ["-c", "copy"]
    cmd += [out_path]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=300)
    except Exception:
        return None
    return storage.url_for(key)


def save_silent_audio(key: str, duration_sec: float) -> Optional[str]:
    """Placeholder voice track so the timeline has real audio in demo mode."""
    if not (settings.ENABLE_LOCAL_RENDER and ffmpeg_available()):
        return None
    storage = get_storage()
    out_path = storage.local_path(key)
    if out_path is None:  # pragma: no cover
        return None
    cmd = [
        settings.FFMPEG_BIN,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r=44100:cl=mono:d={max(duration_sec,1):.2f}",
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        out_path,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
    except Exception:
        return None
    return storage.url_for(key)
