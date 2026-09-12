"""Generate deterministic media fixtures for the media-pipeline tests.

Real customer footage cannot live in the repository, so the tests run against
synthetic stand-ins that behave like real files: true JPEG photos at realistic
aspect ratios, and a short H.264 clip with an audio track and visible shot
changes. Regenerate with:

    python -m tests.fixtures.make_fixtures
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).parent


def _sky(draw: ImageDraw.ImageDraw, w: int, h: int, top: tuple, bottom: tuple) -> None:
    for y in range(h):
        t = y / max(h - 1, 1)
        draw.line(
            [(0, y), (w, y)],
            fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)),
        )


def building_photo(path: Path, w: int, h: int, *, seed: int = 0) -> None:
    """A synthetic 'real estate photo': sky, towers, ground, warm windows."""
    image = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(image)
    _sky(draw, w, h, (118 + seed * 7 % 40, 168, 214), (232, 226, 210))

    ground_y = int(h * 0.78)
    draw.rectangle([0, ground_y, w, h], fill=(96, 98, 94))
    draw.rectangle([0, ground_y, w, ground_y + int(h * 0.02)], fill=(140, 142, 136))

    towers = [
        (0.06, 0.34, 0.30),
        (0.30, 0.52, 0.16),
        (0.46, 0.72, 0.42),
        (0.66, 0.86, 0.24),
    ]
    for index, (x0, x1, top) in enumerate(towers):
        left, right = int(w * x0), int(w * x1)
        top_y = int(h * (top + (seed % 3) * 0.01))
        shade = 196 - index * 22
        draw.rectangle([left, top_y, right, ground_y], fill=(shade, shade - 6, shade - 14))
        draw.rectangle([left, top_y, left + 8, ground_y], fill=(shade + 24, shade + 18, shade + 10))
        step_x, step_y = max((right - left) // 7, 14), max((ground_y - top_y) // 12, 16)
        for wx in range(left + 14, right - 12, step_x):
            for wy in range(top_y + 18, ground_y - 16, step_y):
                lit = ((wx + wy + index * 31 + seed * 13) // 17) % 4 == 0
                draw.rectangle(
                    [wx, wy, wx + step_x - 10, wy + step_y - 10],
                    fill=(250, 214, 150) if lit else (86, 104, 124),
                )
    draw.ellipse(
        [int(w * 0.72), int(h * 0.70), int(w * 0.95), int(h * 0.84)], fill=(74, 116, 74)
    )
    image = image.filter(ImageFilter.SMOOTH)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "JPEG", quality=88)


def interior_photo(path: Path, w: int, h: int) -> None:
    image = Image.new("RGB", (w, h), (236, 230, 220))
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, int(h * 0.62), w, h], fill=(176, 148, 116))
    draw.rectangle([int(w * 0.08), int(h * 0.18), int(w * 0.40), int(h * 0.64)], fill=(206, 224, 236))
    draw.rectangle([int(w * 0.46), int(h * 0.44), int(w * 0.88), int(h * 0.70)], fill=(92, 104, 120))
    draw.ellipse([int(w * 0.60), int(h * 0.12), int(w * 0.70), int(h * 0.22)], fill=(252, 236, 190))
    image.filter(ImageFilter.SMOOTH).save(path, "JPEG", quality=88)


def sample_video(path: Path, ffmpeg: str = "ffmpeg") -> None:
    """12s 1920x1080 clip: three visually distinct shots + a tone track."""
    path.parent.mkdir(parents=True, exist_ok=True)
    graph = (
        "color=c=0x1B3A5C:s=1920x1080:d=4,drawbox=x=200:y=300:w=520:h=480:color=0xE8C07A@1:t=fill[a];"
        "color=c=0x8C5A2B:s=1920x1080:d=4,drawbox=x=1100:y=180:w=620:h=700:color=0xF2EFE6@1:t=fill[b];"
        "color=c=0x2F6B3A:s=1920x1080:d=4,drawbox=x=620:y=520:w=700:h=300:color=0x101820@1:t=fill[c];"
        "[a][b][c]concat=n=3:v=1:a=0,format=yuv420p[v];"
        "sine=frequency=320:duration=12:sample_rate=48000[s];"
        "[s]volume=0.25,aformat=channel_layouts=stereo[aout]"
    )
    subprocess.run(
        [ffmpeg, "-hide_banner", "-nostdin", "-y", "-filter_complex", graph,
         "-map", "[v]", "-map", "[aout]", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "26", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
         "-t", "12", str(path)],
        check=True, capture_output=True, timeout=300,
    )


def voice_like_audio(path: Path, seconds: float = 8.0, ffmpeg: str = "ffmpeg") -> None:
    """Speech-shaped mono audio: enough to exercise ducking and sync."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [ffmpeg, "-hide_banner", "-nostdin", "-y", "-f", "lavfi",
         "-i", f"sine=frequency=180:duration={seconds}:sample_rate=48000",
         "-af", "tremolo=f=4:d=0.8,volume=0.6,highpass=f=90,lowpass=f=3400",
         "-c:a", "aac", "-b:a", "128k", str(path)],
        check=True, capture_output=True, timeout=180,
    )


def music_like_audio(path: Path, seconds: float = 30.0, ffmpeg: str = "ffmpeg") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [ffmpeg, "-hide_banner", "-nostdin", "-y", "-f", "lavfi",
         "-i", f"sine=frequency=110:duration={seconds}:sample_rate=48000",
         "-f", "lavfi", "-i", f"sine=frequency=165:duration={seconds}:sample_rate=48000",
         "-filter_complex", "[0:a][1:a]amix=inputs=2,volume=0.5,aformat=channel_layouts=stereo[a]",
         "-map", "[a]", "-c:a", "aac", "-b:a", "128k", str(path)],
        check=True, capture_output=True, timeout=180,
    )


def logo_png(path: Path, size: int = 512) -> None:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([16, 16, size - 16, size - 16], radius=72, fill=(37, 99, 235, 235))
    draw.rounded_rectangle([size * 0.28, size * 0.30, size * 0.72, size * 0.44], radius=18, fill=(255, 255, 255, 255))
    draw.rounded_rectangle([size * 0.28, size * 0.52, size * 0.58, size * 0.66], radius=18, fill=(255, 255, 255, 235))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG")


def build_all() -> dict:
    paths = {
        "photo_landscape": HERE / "photo_landscape.jpg",
        "photo_landscape_2": HERE / "photo_landscape_2.jpg",
        "photo_portrait": HERE / "photo_portrait.jpg",
        "photo_interior": HERE / "photo_interior.jpg",
        "video": HERE / "sample_video.mp4",
        "voice": HERE / "voice.m4a",
        "music": HERE / "music.m4a",
        "logo": HERE / "logo.png",
    }
    building_photo(paths["photo_landscape"], 1920, 1080, seed=1)
    building_photo(paths["photo_landscape_2"], 1600, 1067, seed=5)
    building_photo(paths["photo_portrait"], 1080, 1440, seed=3)
    interior_photo(paths["photo_interior"], 1600, 1200)
    sample_video(paths["video"])
    voice_like_audio(paths["voice"])
    music_like_audio(paths["music"])
    logo_png(paths["logo"])
    return {k: str(v) for k, v in paths.items()}


if __name__ == "__main__":  # pragma: no cover
    for name, path in build_all().items():
        print(f"{name:20s} {path}")
