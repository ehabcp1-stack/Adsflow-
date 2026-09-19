"""Final assembly: scene clips + captions + brand + audio -> one finished reel.

The pipeline is deliberately staged rather than one giant filtergraph, because
when a render fails the job record has to say *which* stage failed. Each stage
writes a real file that can be inspected.

    1. picture   — normalise and concatenate scene clips (+ end screen)
    2. overlays  — burn captions, logo and CTA at timeline positions
    3. audio     — build the voice/music/SFX bed and master it
    4. mux       — attach the bed, write a fast-start MP4
"""
from __future__ import annotations

import logging
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from app.media.audio import AudioMixSpec, attach_audio, measure_loudness, mix_audio
from app.media.captions import CaptionStyle, render_caption_track
from app.media.ffmpeg import (
    AUDIO_ENCODE,
    INTERMEDIATE_VIDEO_ENCODE,
    OUT_FPS,
    OUT_HEIGHT,
    OUT_SAMPLE_RATE,
    OUT_WIDTH,
    VIDEO_ENCODE,
    ensure_parent,
    run_ffmpeg,
)
from app.media.overlays import (
    BrandLayer,
    TimedOverlay,
    build_overlay_graph,
    logo_xy,
    prepare_logo,
    render_cta_card,
    render_end_screen,
    safe_zone,
)
from app.media.probe import probe_media
from app.media.remix import concat_clips

log = logging.getLogger("adflow.media.assemble")


@dataclass
class AssemblySpec:
    """Everything the renderer needs. Built by services/editing.py."""

    scene_clips: List[str] = field(default_factory=list)
    captions: List[Dict[str, Any]] = field(default_factory=list)
    caption_style: Optional[CaptionStyle] = None
    captions_enabled: bool = True
    brand: Optional[BrandLayer] = None
    branding_enabled: bool = True
    cta_enabled: bool = True
    cta_text: str = ""
    cta_lead_sec: float = 3.2
    end_screen_enabled: bool = True
    end_screen_sec: float = 2.6
    platform: str = "instagram_reels"
    voice_path: Optional[str] = None
    music_path: Optional[str] = None
    sfx: List[Dict[str, Any]] = field(default_factory=list)
    voice_volume: float = 1.0
    music_volume: float = 0.22
    duck_music_under_voice: bool = True
    #: The editing style's scene transition, and how long it lasts. `remix.
    #: concat_clips` draws it without changing the running time, so the picture
    #: stays on the voice it was cut to.
    transition: str = "cut"
    transition_sec: float = 0.35
    width: int = OUT_WIDTH
    height: int = OUT_HEIGHT
    fps: int = OUT_FPS


def _still_to_clip(image_path: str, out_path: str, duration: float, *,
                   width: int, height: int, fps: int) -> str:
    """Turn a rendered card (end screen) into a clip that concatenates cleanly."""
    ensure_parent(out_path)
    run_ffmpeg(
        ["-loop", "1", "-framerate", str(fps), "-t", f"{duration:.3f}", "-i", image_path,
         "-f", "lavfi", "-t", f"{duration:.3f}", "-i", f"anullsrc=r={OUT_SAMPLE_RATE}:cl=stereo",
         "-vf", (f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                 f"crop={width}:{height},fps={fps},setsar=1,format=yuv420p,"
                 f"fade=t=in:st=0:d=0.35"),
         "-t", f"{duration:.3f}", *INTERMEDIATE_VIDEO_ENCODE, *AUDIO_ENCODE, out_path],
        label="assemble:endscreen", timeout=300,
    )
    return out_path


#: How many overlays go into one FFmpeg invocation.
#:
#: Every overlay is a `-loop 1 -i <png>` — its own decoder and RGBA buffer,
#: and they are all alive at once, so the memory of this stage is linear in
#: the number of overlays. Measured on a 19s 1080x1920 reel (peak RSS of the
#: FFmpeg child):
#:
#:     inputs   full-frame PNGs      cropped PNGs
#:     10       638 MB / 27.6s       308 MB / 9.8s
#:     46       1973 MB / 91.6s      824 MB / 35.6s
#:     70       ~2.9 GB (extrap.)    1169 MB / 52.0s
#:
#: Cropping each caption to the card that was drawn (see `media/captions.py`)
#: took the slope from ~37 MB to ~14 MB per input. That is most of the fix,
#: and it changes nothing about the picture — the cropped render is the same
#: file, md5 for md5.
#:
#: It is not all of it. Word-level captions make one overlay per word, so the
#: count follows the script, and nothing stops a longer one from climbing back
#: out of whatever the container will give us. A burn split into passes has a
#: ceiling instead of a slope. Measured on the same reel, 30 overlays:
#:
#:     one pass       894.6 MB / 32.7s
#:     four passes    435.2 MB / 37.8s     PSNR 53.6 dB against the one-pass
#:
#: Half the memory for a sixth more time, and a difference no one can see —
#: 53 dB is the extra intermediate encode, not a visible change. Twelve keeps
#: the ceiling near 500 MB whatever the script length turns out to be.
OVERLAY_CHUNK = 12


def _burn_overlays(picture_path: str, overlays: Sequence[TimedOverlay], out_path: str,
                   *, duration: float) -> str:
    """Burn the overlays on, in as few passes as the memory ceiling allows."""
    if not overlays:
        shutil.copyfile(picture_path, out_path)
        return out_path

    chunks = [list(overlays[i:i + OVERLAY_CHUNK]) for i in range(0, len(overlays), OVERLAY_CHUNK)]
    ensure_parent(out_path)
    source = picture_path
    staging: List[str] = []

    for number, chunk in enumerate(chunks):
        last = number == len(chunks) - 1
        target = out_path if last else f"{out_path}.pass{number}.mp4"
        graph, inputs = build_overlay_graph(chunk, base_label="0:v", out_label="vout")
        # Only the final pass gets the delivery encode; the ones feeding
        # another pass use the fast intermediate settings, as everywhere else
        # in this package.
        encode = VIDEO_ENCODE if last else INTERMEDIATE_VIDEO_ENCODE
        args = ["-i", source, *inputs,
                "-filter_complex", graph, "-map", "[vout]", "-map", "0:a?",
                "-t", f"{duration:.3f}", *encode, "-c:a", "copy", target]
        run_ffmpeg(
            args,
            label="assemble:overlays" if len(chunks) == 1 else f"assemble:overlays[{number + 1}/{len(chunks)}]",
            timeout=900,
        )
        if not last:
            staging.append(target)
        source = target

    for leftover in staging:
        Path(leftover).unlink(missing_ok=True)
    return out_path


def assemble_reel(spec: AssemblySpec, out_path: str, *,
                  work_dir: Optional[str] = None,
                  progress: Optional[Any] = None) -> Dict[str, Any]:
    """Render the finished ad. Returns a stage-by-stage report."""
    clips = [c for c in spec.scene_clips if c and Path(c).exists()]
    if not clips:
        raise ValueError("assembly needs at least one scene clip")

    temp_dir = work_dir or tempfile.mkdtemp(prefix="adflow-render-")
    Path(temp_dir).mkdir(parents=True, exist_ok=True)
    report: Dict[str, Any] = {"stages": {}, "warnings": []}

    def step(fraction: float, label: str) -> None:
        if progress:
            try:
                progress(fraction, label)
            except Exception:  # noqa: BLE001 - progress must never break a render
                pass

    # ---- 1. picture -----------------------------------------------------
    step(0.10, "building picture")
    render_clips = list(clips)
    end_screen_info: Optional[Dict[str, Any]] = None
    if spec.end_screen_enabled and spec.brand:
        try:
            card = render_end_screen(str(Path(temp_dir) / "end_screen.png"), spec.brand,
                                     width=spec.width, height=spec.height)
            end_clip = _still_to_clip(card["path"], str(Path(temp_dir) / "end_screen.mp4"),
                                      spec.end_screen_sec, width=spec.width,
                                      height=spec.height, fps=spec.fps)
            render_clips.append(end_clip)
            end_screen_info = card
        except Exception as exc:  # noqa: BLE001
            log.warning("end screen failed: %s", exc)
            report["warnings"].append(f"end screen skipped: {exc}")

    picture = str(Path(temp_dir) / "picture.mp4")
    concat_result = concat_clips(render_clips, picture, width=spec.width,
                                 height=spec.height, fps=spec.fps,
                                 transition=spec.transition,
                                 transition_sec=spec.transition_sec)
    duration = float(concat_result["duration_sec"] or 0.0)
    report["stages"]["picture"] = {**concat_result, "end_screen": bool(end_screen_info)}

    # ---- 2. overlays ----------------------------------------------------
    step(0.40, "burning captions and branding")
    overlays: List[TimedOverlay] = []
    caption_report: List[Dict[str, Any]] = []
    body_duration = duration - (spec.end_screen_sec if end_screen_info else 0.0)

    # The CTA card and the caption bar occupy the same lower third. Captions
    # stop where the CTA begins so the two never stack on top of each other.
    cta_text_planned = spec.cta_text or (spec.brand.cta_text if spec.brand else "")
    cta_will_show = bool(
        spec.cta_enabled and spec.brand and (cta_text_planned or spec.brand.phone)
    )
    cta_start = max(body_duration - spec.cta_lead_sec, 0.0) if cta_will_show else body_duration
    caption_limit = cta_start if cta_will_show else body_duration

    if spec.captions_enabled and spec.captions:
        style = spec.caption_style or CaptionStyle()
        zone = safe_zone(spec.platform)
        style.safe_bottom_pct = max(style.safe_bottom_pct, zone["bottom"] * 100)
        style.safe_top_pct = max(style.safe_top_pct, zone["top"] * 100)
        rendered = render_caption_track(spec.captions, str(Path(temp_dir) / "captions"),
                                        style=style, width=spec.width, height=spec.height)
        for item in rendered:
            start = float(item.get("start", 0.0) or 0.0)
            end = float(item.get("end", start + 2.0) or start + 2.0)
            end = min(end, caption_limit)
            # A caption clipped to a flash is worse than no caption. The last
            # script line is normally the CTA, which the CTA card already says.
            #
            # Word-level frames are the exception: each is a fraction of a
            # second by design, because the card stays put while the highlight
            # moves across it. Judging them by the whole-card floor would drop
            # every one of them and burn no captions at all.
            floor = 0.08 if item.get("highlight_index") is not None else 0.8
            if end <= start + floor:
                continue
            # Only the edges of a cue fade. A word-level run is one card whose
            # highlight moves; fading every frame in and out cross-dissolves
            # two identical cards eight times a line, which reads as the text
            # blinking. Measured in the rendered file, not in the PNGs.
            geometry = item.get("geometry") or {}
            overlays.append(TimedOverlay(
                png=item["png"], start=start, end=end,
                # The PNG is cropped to the card; this is where the card sat.
                x=str(int(geometry.get("offset_x", 0))),
                y=str(int(geometry.get("offset_y", 0))),
                fade_in=None if item.get("cue_first", True) else 0.0,
                fade_out=None if item.get("cue_last", True) else 0.0,
            ))
            caption_report.append({
                "text": item.get("text"),
                "start": start,
                "end": round(end, 2),
                "lines": item["geometry"]["line_count"],
                "within_safe_zone": item["geometry"]["within_safe_zone"],
                "rtl": item["geometry"]["rtl"],
            })

    logo_ready: Optional[str] = None
    if spec.branding_enabled and spec.brand and spec.brand.logo_path:
        logo_ready = prepare_logo(spec.brand.logo_path, str(Path(temp_dir) / "logo.png"),
                                  max_width=int(spec.width * 0.22),
                                  opacity=spec.brand.watermark_opacity)
        if logo_ready:
            from PIL import Image as _Image

            with _Image.open(logo_ready) as logo_image:
                lx, ly = logo_xy(spec.brand.logo_position, logo_width=logo_image.width,
                                 logo_height=logo_image.height, platform=spec.platform,
                                 width=spec.width, height=spec.height)
            overlays.append(TimedOverlay(png=logo_ready, start=0.0,
                                         end=max(body_duration, 0.5), x=str(lx), y=str(ly), fade=0.4))

    cta_info: Optional[Dict[str, Any]] = None
    if cta_will_show:
        try:
            cta_info = render_cta_card(str(Path(temp_dir) / "cta.png"), spec.brand,
                                       cta_text=cta_text_planned, platform=spec.platform,
                                       width=spec.width, height=spec.height)
            overlays.append(TimedOverlay(png=cta_info["path"], start=cta_start,
                                         end=max(body_duration, cta_start + 0.5), x="0", y="0", fade=0.3))
        except Exception as exc:  # noqa: BLE001
            log.warning("CTA card failed: %s", exc)
            report["warnings"].append(f"CTA skipped: {exc}")

    overlaid = str(Path(temp_dir) / "overlaid.mp4")
    _burn_overlays(picture, overlays, overlaid, duration=duration)
    report["stages"]["overlays"] = {
        "count": len(overlays),
        "captions": caption_report,
        "logo": bool(logo_ready),
        "cta": bool(cta_info),
        "end_screen": end_screen_info,
    }

    # ---- 3. audio -------------------------------------------------------
    step(0.70, "mixing audio")
    bed = str(Path(temp_dir) / "audio.m4a")
    mix_spec = AudioMixSpec(
        voice_path=spec.voice_path, music_path=spec.music_path, sfx=list(spec.sfx),
        duration_sec=duration, voice_volume=spec.voice_volume,
        music_volume=spec.music_volume, duck_music_under_voice=spec.duck_music_under_voice,
    )
    audio_report = mix_audio(mix_spec, bed)
    report["stages"]["audio"] = audio_report

    # ---- 4. mux ---------------------------------------------------------
    step(0.90, "writing final file")
    ensure_parent(out_path)
    mux_report = attach_audio(overlaid, bed, out_path, duration_sec=duration)
    info = probe_media(out_path)
    report["stages"]["mux"] = mux_report
    report.update({
        "path": out_path,
        "duration_sec": info.duration_sec,
        "width": info.width,
        "height": info.height,
        "fps": info.fps,
        "video_codec": info.video_codec,
        "audio_codec": info.audio_codec,
        "has_audio": info.has_audio,
        "size_bytes": info.size_bytes,
        "loudness": measure_loudness(out_path),
        "work_dir": temp_dir,
    })
    step(1.0, "completed")
    return report


def make_thumbnail(video_path: str, out_path: str, *, at_sec: float = 1.0,
                   width: int = OUT_WIDTH, height: int = OUT_HEIGHT) -> Optional[str]:
    """Cover image for the export screen and social upload."""
    try:
        ensure_parent(out_path)
        run_ffmpeg(
            ["-ss", f"{max(at_sec, 0):.3f}", "-i", video_path, "-frames:v", "1",
             "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}",
             "-update", "1", out_path],
            label="assemble:thumbnail", timeout=120,
        )
        return out_path if Path(out_path).exists() else None
    except Exception as exc:  # noqa: BLE001
        log.warning("thumbnail failed: %s", exc)
        return None
