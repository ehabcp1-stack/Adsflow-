"""Real demo media for the seeded «مدينة الورد» project.

The demo project has to exercise the *real* pipeline, not a drawing of it. If
its assets were vector placeholders, photo motion would have nothing to pan
across, the remix path would have no footage to cut, and QC would be grading a
file that was never really produced. So the seeder generates genuine JPEG
photographs, a genuine H.264 site-tour clip with an audio track, a PNG logo and
speech-shaped voice and music beds.

They are synthesised rather than photographed — this is a demo, and shipping
someone's real project photography in a public repository would not be ours to
do — but they are real files with real pixels, real shot changes and real
audio, which is what the pipeline needs.
"""
from __future__ import annotations

import logging
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter

from app.core.config import settings
from app.media.ffmpeg import ffmpeg_available
from app.services.storage import get_storage

log = logging.getLogger("adflow.seed_media")


@dataclass
class DemoPhoto:
    key: str
    category: str
    title_ar: str
    subtitle: str
    width: int
    height: int
    scene: str
    is_reference: bool = False


DEMO_PHOTOS: List[DemoPhoto] = [
    DemoPhoto("exterior-golden", "exterior", "واجهة المشروع", "Exterior — golden hour", 2400, 1600, "skyline_sunset", True),
    DemoPhoto("entrance", "exterior", "مدخل رئيسي", "Main entrance", 2400, 1600, "entrance", True),
    DemoPhoto("living", "interior", "صالة معيشة", "Living area", 2000, 1500, "living", True),
    DemoPhoto("kitchen", "interior", "مطبخ مفتوح", "Open kitchen", 2000, 1500, "kitchen"),
    DemoPhoto("gardens", "amenity", "حدائق ومسارات", "Green walkways", 2400, 1600, "gardens"),
    DemoPhoto("pool", "amenity", "نادي ومسبح", "Club & pool", 2400, 1600, "pool"),
    DemoPhoto("tower-portrait", "exterior", "البرج من الشارع", "Tower from street", 1620, 2160, "skyline_day"),
    DemoPhoto("detail", "detail", "تفاصيل التشطيب", "Finishing detail", 2000, 1500, "detail"),
]


def _gradient(draw: ImageDraw.ImageDraw, w: int, h: int, top: Tuple[int, int, int],
              bottom: Tuple[int, int, int], until: Optional[int] = None) -> None:
    end = until or h
    for y in range(end):
        t = y / max(end - 1, 1)
        draw.line([(0, y), (w, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))


def _towers(draw: ImageDraw.ImageDraw, w: int, h: int, ground: int, *, warm: bool,
            seed: int = 0) -> None:
    blocks = [(0.02, 0.20, 0.40), (0.18, 0.36, 0.22), (0.34, 0.58, 0.50),
              (0.55, 0.74, 0.30), (0.72, 0.99, 0.44)]
    for index, (x0, x1, top) in enumerate(blocks):
        left, right = int(w * x0), int(w * x1)
        top_y = int(h * (top + ((index + seed) % 3) * 0.015))
        base = 210 - index * 18
        tint = (base, base - 8, base - 20) if warm else (base - 16, base - 8, base)
        draw.rectangle([left, top_y, right, ground], fill=tint)
        draw.rectangle([left, top_y, left + max(w // 220, 4), ground],
                       fill=tuple(min(c + 28, 255) for c in tint))
        step_x = max((right - left) // 8, 18)
        step_y = max((ground - top_y) // 14, 20)
        for wx in range(left + step_x // 3, right - step_x // 3, step_x):
            for wy in range(top_y + step_y, ground - step_y, step_y):
                lit = ((wx * 7 + wy * 3 + index * 31 + seed * 13) // 29) % 5 < 2
                glass = (252, 214, 148) if (lit and warm) else (236, 240, 246) if lit else (72, 92, 116)
                draw.rectangle([wx, wy, wx + step_x - step_x // 3, wy + step_y - step_y // 2], fill=glass)


def _trees(draw: ImageDraw.ImageDraw, w: int, h: int, ground: int, count: int = 9) -> None:
    for i in range(count):
        x = int(w * (0.05 + 0.9 * i / max(count - 1, 1)))
        size = int(h * (0.05 + 0.02 * ((i * 5) % 3)))
        draw.rectangle([x - size // 10, ground - size // 2, x + size // 10, ground], fill=(96, 74, 52))
        draw.ellipse([x - size, ground - size * 2, x + size, ground - size // 2],
                     fill=(48 + (i * 9) % 30, 112 + (i * 7) % 30, 56))


def _photo(scene: str, w: int, h: int, seed: int) -> Image.Image:
    image = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(image)
    ground = int(h * 0.80)

    if scene == "skyline_sunset":
        _gradient(draw, w, h, (246, 170, 96), (252, 232, 198), until=ground)
        draw.ellipse([int(w * 0.62), int(h * 0.14), int(w * 0.78), int(h * 0.38)], fill=(255, 226, 168))
        draw.rectangle([0, ground, w, h], fill=(86, 84, 78))
        _towers(draw, w, h, ground, warm=True, seed=seed)
        _trees(draw, w, h, ground, 7)
    elif scene == "skyline_day":
        _gradient(draw, w, h, (104, 162, 214), (214, 232, 244), until=ground)
        draw.rectangle([0, ground, w, h], fill=(96, 96, 92))
        _towers(draw, w, h, ground, warm=False, seed=seed)
        _trees(draw, w, h, ground, 5)
    elif scene == "entrance":
        _gradient(draw, w, h, (128, 178, 220), (226, 236, 242), until=int(h * 0.42))
        draw.rectangle([0, int(h * 0.42), w, h], fill=(206, 198, 184))
        draw.rectangle([int(w * 0.16), int(h * 0.16), int(w * 0.84), int(h * 0.86)], fill=(228, 222, 210))
        draw.rectangle([int(w * 0.32), int(h * 0.40), int(w * 0.68), int(h * 0.86)], fill=(72, 104, 132))
        for x in (0.22, 0.74):
            draw.rectangle([int(w * x), int(h * 0.30), int(w * (x + 0.045)), int(h * 0.86)], fill=(246, 242, 236))
        draw.rectangle([int(w * 0.28), int(h * 0.22), int(w * 0.72), int(h * 0.30)], fill=(38, 62, 92))
        _trees(draw, w, h, int(h * 0.88), 4)
    elif scene == "living":
        draw.rectangle([0, 0, w, h], fill=(238, 232, 222))
        draw.rectangle([0, int(h * 0.70), w, h], fill=(186, 154, 118))
        draw.rectangle([int(w * 0.04), int(h * 0.12), int(w * 0.38), int(h * 0.72)], fill=(198, 222, 238))
        draw.rectangle([int(w * 0.44), int(h * 0.46), int(w * 0.92), int(h * 0.74)], fill=(94, 106, 122))
        draw.rectangle([int(w * 0.50), int(h * 0.76), int(w * 0.84), int(h * 0.82)], fill=(140, 112, 84))
        draw.ellipse([int(w * 0.60), int(h * 0.10), int(w * 0.70), int(h * 0.20)], fill=(252, 238, 194))
    elif scene == "kitchen":
        draw.rectangle([0, 0, w, h], fill=(244, 242, 238))
        draw.rectangle([0, int(h * 0.62), w, int(h * 0.70)], fill=(58, 62, 70))
        draw.rectangle([0, int(h * 0.70), w, h], fill=(212, 206, 196))
        draw.rectangle([int(w * 0.06), int(h * 0.16), int(w * 0.46), int(h * 0.52)], fill=(226, 222, 214))
        draw.rectangle([int(w * 0.54), int(h * 0.10), int(w * 0.94), int(h * 0.56)], fill=(196, 216, 232))
        for i in range(5):
            x = int(w * (0.10 + i * 0.17))
            draw.rectangle([x, int(h * 0.72), x + int(w * 0.12), int(h * 0.94)], fill=(230, 226, 218))
    elif scene == "gardens":
        _gradient(draw, w, h, (140, 190, 226), (222, 238, 246), until=int(h * 0.44))
        draw.rectangle([0, int(h * 0.44), w, h], fill=(74, 126, 66))
        draw.polygon([(int(w * 0.30), h), (int(w * 0.46), int(h * 0.46)),
                      (int(w * 0.56), int(h * 0.46)), (int(w * 0.74), h)], fill=(214, 206, 190))
        _trees(draw, w, h, int(h * 0.92), 11)
    elif scene == "pool":
        _gradient(draw, w, h, (138, 188, 224), (226, 238, 246), until=int(h * 0.38))
        draw.rectangle([0, int(h * 0.38), w, h], fill=(226, 220, 208))
        draw.rounded_rectangle([int(w * 0.10), int(h * 0.52), int(w * 0.90), int(h * 0.92)],
                               radius=int(h * 0.05), fill=(62, 156, 196))
        for i in range(7):
            y = int(h * (0.58 + i * 0.045))
            draw.line([(int(w * 0.14), y), (int(w * 0.86), y)], fill=(120, 196, 224), width=max(h // 260, 3))
        _trees(draw, w, h, int(h * 0.50), 6)
    else:  # detail
        draw.rectangle([0, 0, w, h], fill=(224, 216, 202))
        for i in range(14):
            x = int(w * i / 14)
            shade = 206 + (i % 3) * 12
            draw.rectangle([x, 0, x + w // 15, h], fill=(shade, shade - 10, shade - 24))
        draw.rectangle([int(w * 0.10), int(h * 0.30), int(w * 0.90), int(h * 0.70)], fill=(58, 70, 84))
        draw.rectangle([int(w * 0.13), int(h * 0.33), int(w * 0.87), int(h * 0.67)], fill=(178, 200, 216))

    return image.filter(ImageFilter.SMOOTH_MORE)


def _write_photo(photo: DemoPhoto, project_id: str, seed: int) -> Dict[str, Any]:
    storage = get_storage()
    key = f"demo/{project_id}/{photo.key}.jpg"
    target = storage.local_path(key)
    image = _photo(photo.scene, photo.width, photo.height, seed)
    if target:
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        image.save(target, "JPEG", quality=86)
        url = storage.url_for(key)
        size = Path(target).stat().st_size
    else:  # pragma: no cover - object storage
        import io

        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=86)
        data = buffer.getvalue()
        url = storage.put_bytes(key, data, "image/jpeg")
        size = len(data)
    return {"key": key, "url": url, "size_bytes": size,
            "width": photo.width, "height": photo.height}


def _run(cmd: List[str], timeout: int = 300) -> bool:
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=timeout)
        return True
    except Exception as exc:  # noqa: BLE001 - seeding must never hard-fail
        log.warning("seed media command failed: %s", exc)
        return False


def _site_tour(project_id: str) -> Optional[Dict[str, Any]]:
    """A landscape site-tour clip with three shots — real material to remix."""
    if not ffmpeg_available():
        return None
    storage = get_storage()
    key = f"demo/{project_id}/site-tour.mp4"
    target = storage.local_path(key)
    if not target:  # pragma: no cover - object storage
        return None
    Path(target).parent.mkdir(parents=True, exist_ok=True)

    stills: List[str] = []
    base = Path(target).parent
    for index, scene in enumerate(("skyline_sunset", "gardens", "pool")):
        still = base / f"tour-shot-{index}.jpg"
        _photo(scene, 1920, 1080, seed=index + 4).save(still, "JPEG", quality=86)
        stills.append(str(still))

    graph_parts = []
    for index in range(3):
        graph_parts.append(
            f"[{index}:v]scale=1920:1080,setsar=1,fps=30,"
            f"zoompan=z='min(1+0.0009*on,1.10)':d=120:s=1920x1080:fps=30[v{index}]"
        )
    graph_parts.append("[v0][v1][v2]concat=n=3:v=1:a=0,format=yuv420p[v]")
    graph_parts.append("sine=frequency=220:duration=12:sample_rate=48000,volume=0.18,"
                       "aformat=channel_layouts=stereo[a]")
    args = [settings.FFMPEG_BIN, "-hide_banner", "-nostdin", "-y"]
    for still in stills:
        args += ["-loop", "1", "-framerate", "30", "-t", "4", "-i", still]
    args += ["-filter_complex", ";".join(graph_parts), "-map", "[v]", "-map", "[a]",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "128k", "-t", "12", "-movflags", "+faststart", target]
    if not _run(args):
        return None
    for still in stills:
        Path(still).unlink(missing_ok=True)
    return {"key": key, "url": storage.url_for(key),
            "size_bytes": Path(target).stat().st_size,
            "width": 1920, "height": 1080, "duration_sec": 12.0}


def _logo(project_id: str) -> Optional[Dict[str, Any]]:
    storage = get_storage()
    key = f"demo/{project_id}/logo.png"
    target = storage.local_path(key)
    size = 640
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([24, 24, size - 24, size - 24], radius=96, fill=(15, 23, 42, 240))
    for index in range(3):
        inset = size * (0.26 + index * 0.10)
        length = size * (0.48 - index * 0.11)
        draw.rounded_rectangle([inset, size * (0.30 + index * 0.15), inset + length,
                                size * (0.30 + index * 0.15) + size * 0.085],
                               radius=size * 0.04, fill=(37, 99, 235, 255))
    draw.ellipse([size * 0.62, size * 0.20, size * 0.80, size * 0.38], fill=(244, 197, 94, 255))
    if target:
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        image.save(target, "PNG")
        return {"key": key, "url": storage.url_for(key), "size_bytes": Path(target).stat().st_size,
                "width": size, "height": size}
    import io  # pragma: no cover - object storage

    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return {"key": key, "url": storage.put_bytes(key, buffer.getvalue(), "image/png"),
            "size_bytes": buffer.tell(), "width": size, "height": size}


def _audio(project_id: str, name: str, filters: str, duration: float) -> Optional[Dict[str, Any]]:
    if not ffmpeg_available():
        return None
    storage = get_storage()
    key = f"demo/{project_id}/{name}.m4a"
    target = storage.local_path(key)
    if not target:  # pragma: no cover
        return None
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    args = [settings.FFMPEG_BIN, "-hide_banner", "-nostdin", "-y",
            "-f", "lavfi", "-i", f"sine=frequency=180:duration={duration}:sample_rate=48000",
            "-af", filters, "-c:a", "aac", "-b:a", "128k", target]
    if not _run(args):
        return None
    return {"key": key, "url": storage.url_for(key),
            "size_bytes": Path(target).stat().st_size, "duration_sec": duration}


def demo_voice(project_id: str, duration: float = 22.0) -> Optional[Dict[str, Any]]:
    """Speech-shaped placeholder VO so the mix, ducking and QC are real."""
    return _audio(project_id, "voice-demo",
                  "tremolo=f=4.2:d=0.85,volume=0.62,highpass=f=95,lowpass=f=3600", duration)


def demo_music(project_id: str, duration: float = 32.0) -> Optional[Dict[str, Any]]:
    return _audio(project_id, "music-demo",
                  "aeval=val(0)*0.6|val(0)*0.6,volume=0.45,lowpass=f=6000,aformat=channel_layouts=stereo",
                  duration)


def build_demo_media(project_id: str) -> Dict[str, Any]:
    """Generate every demo file once. Returns records keyed by purpose."""
    photos = [
        {**_write_photo(photo, project_id, index), "meta": photo}
        for index, photo in enumerate(DEMO_PHOTOS)
    ]
    return {
        "photos": photos,
        "video": _site_tour(project_id),
        "logo": _logo(project_id),
        "voice": demo_voice(project_id),
        "music": demo_music(project_id),
    }
