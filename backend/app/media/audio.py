"""Audio engine: voice, music, SFX, ducking and mastering.

The Iraqi voice-over is the message. Everything else exists to support it, so
the mix is built voice-first: music sits under it, ducks automatically when it
speaks, and the whole bed is loudness-normalised so one reel is not twice as
loud as the next in a feed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from app.media.ffmpeg import OUT_SAMPLE_RATE, capabilities, ensure_parent, run_ffmpeg
from app.media.probe import probe_media

log = logging.getLogger("adflow.media.audio")

#: Broadcast-ish target. -14 LUFS is the level social platforms normalise to,
#: so mastering here avoids the platform doing something less careful.
TARGET_LUFS = -14.0
TRUE_PEAK = -1.5
LOUDNESS_RANGE = 11.0


@dataclass
class AudioMixSpec:
    voice_path: Optional[str] = None
    music_path: Optional[str] = None
    sfx: List[Dict[str, Any]] = field(default_factory=list)  # {path, at, gain}
    duration_sec: float = 30.0
    voice_volume: float = 1.0
    music_volume: float = 0.22
    sfx_volume: float = 0.5
    duck_music_under_voice: bool = True
    duck_ratio: float = 8.0
    duck_threshold: float = 0.035
    music_fade_in: float = 0.6
    music_fade_out: float = 1.2
    master: bool = True


def _duck_chain(spec: AudioMixSpec) -> str:
    """Sidechain compression: music volume follows the voice envelope."""
    return (
        f"sidechaincompress=threshold={spec.duck_threshold}:ratio={spec.duck_ratio}"
        f":attack=12:release=320:makeup=1"
    )


def build_mix_graph(spec: AudioMixSpec, *, inputs: Sequence[str]) -> str:
    """Build the audio filtergraph for the given ordered inputs.

    ``inputs`` lists the roles in input order: "voice", "music", "sfx".
    """
    duration = max(spec.duration_sec, 0.5)
    parts: List[str] = []
    mix_labels: List[str] = []
    index_of: Dict[str, int] = {}
    sfx_indices: List[int] = []
    for index, role in enumerate(inputs):
        if role == "sfx":
            sfx_indices.append(index)
        else:
            index_of[role] = index

    has_voice = "voice" in index_of
    has_music = "music" in index_of

    if has_voice:
        parts.append(
            f"[{index_of['voice']}:a]aresample={OUT_SAMPLE_RATE},aformat=channel_layouts=stereo,"
            f"highpass=f=85,volume={spec.voice_volume:.3f},"
            f"acompressor=threshold=0.12:ratio=3:attack=8:release=180,"
            f"apad=whole_dur={duration:.3f},atrim=0:{duration:.3f},asetpts=PTS-STARTPTS[voice]"
        )

    if has_music:
        music_chain = (
            f"[{index_of['music']}:a]aresample={OUT_SAMPLE_RATE},aformat=channel_layouts=stereo,"
            f"volume={spec.music_volume:.3f},"
            f"afade=t=in:st=0:d={spec.music_fade_in:.2f},"
            f"afade=t=out:st={max(duration - spec.music_fade_out, 0):.2f}:d={spec.music_fade_out:.2f},"
            f"apad=whole_dur={duration:.3f},atrim=0:{duration:.3f},asetpts=PTS-STARTPTS[music_raw]"
        )
        parts.append(music_chain)
        if has_voice and spec.duck_music_under_voice and capabilities().has_filter("sidechaincompress"):
            # The voice is needed twice: once as the mix element, once as the
            # ducking key, so it is split rather than consumed.
            parts.append("[voice]asplit=2[voice_mix][voice_key]")
            parts.append(f"[music_raw][voice_key]{_duck_chain(spec)}[music]")
            mix_labels += ["[voice_mix]", "[music]"]
        else:
            parts.append("[music_raw]anull[music]")
            if has_voice:
                mix_labels.append("[voice]")
            mix_labels.append("[music]")
    elif has_voice:
        mix_labels.append("[voice]")

    for order, index in enumerate(sfx_indices):
        cue = spec.sfx[order] if order < len(spec.sfx) else {}
        at = float(cue.get("at", 0.0) or 0.0)
        gain = float(cue.get("gain", spec.sfx_volume) or spec.sfx_volume)
        label = f"sfx{order}"
        parts.append(
            f"[{index}:a]aresample={OUT_SAMPLE_RATE},aformat=channel_layouts=stereo,"
            f"volume={gain:.3f},adelay={int(at * 1000)}|{int(at * 1000)},"
            f"apad=whole_dur={duration:.3f},atrim=0:{duration:.3f},asetpts=PTS-STARTPTS[{label}]"
        )
        mix_labels.append(f"[{label}]")

    if not mix_labels:
        raise ValueError("audio mix has no sources")

    if len(mix_labels) == 1:
        parts.append(f"{mix_labels[0]}anull[mixed]")
    else:
        parts.append(
            f"{''.join(mix_labels)}amix=inputs={len(mix_labels)}:duration=longest"
            f":dropout_transition=0:normalize=0[mixed]"
        )

    tail = "[mixed]"
    if spec.master and capabilities().has_filter("loudnorm"):
        parts.append(
            f"[mixed]loudnorm=I={TARGET_LUFS}:TP={TRUE_PEAK}:LRA={LOUDNESS_RANGE},"
            f"alimiter=limit=0.97,aresample={OUT_SAMPLE_RATE}[aout]"
        )
        tail = "[aout]"
    else:
        parts.append(f"[mixed]alimiter=limit=0.97[aout]")
        tail = "[aout]"
    return ";".join(parts)


def mix_audio(spec: AudioMixSpec, out_path: str) -> Dict[str, Any]:
    """Render the final audio bed to an .m4a file."""
    args: List[str] = []
    roles: List[str] = []
    if spec.voice_path and Path(spec.voice_path).exists():
        args += ["-i", spec.voice_path]
        roles.append("voice")
    if spec.music_path and Path(spec.music_path).exists():
        args += ["-stream_loop", "-1", "-i", spec.music_path]
        roles.append("music")
    usable_sfx: List[Dict[str, Any]] = []
    for cue in spec.sfx:
        path = cue.get("path")
        if path and Path(path).exists():
            args += ["-i", path]
            roles.append("sfx")
            usable_sfx.append(cue)
    spec.sfx = usable_sfx

    if not roles:
        # Silence is a legitimate outcome (a muted reel) and must still produce
        # a valid stream so the muxer has something to work with.
        ensure_parent(out_path)
        run_ffmpeg(
            ["-f", "lavfi", "-t", f"{spec.duration_sec:.3f}",
             "-i", f"anullsrc=r={OUT_SAMPLE_RATE}:cl=stereo",
             "-c:a", "aac", "-b:a", "128k", out_path],
            label="audio:silence", timeout=180,
        )
        return {"path": out_path, "sources": [], "silent": True,
                "duration_sec": spec.duration_sec, "ducked": False}

    graph = build_mix_graph(spec, inputs=roles)
    ensure_parent(out_path)
    args += ["-filter_complex", graph, "-map", "[aout]",
             "-t", f"{spec.duration_sec:.3f}",
             "-c:a", "aac", "-b:a", "192k", "-ar", str(OUT_SAMPLE_RATE), "-ac", "2", out_path]
    run_ffmpeg(args, label="audio:mix", timeout=600)

    info = probe_media(out_path)
    return {
        "path": out_path,
        "sources": roles,
        "silent": False,
        "duration_sec": info.duration_sec,
        "ducked": bool("voice" in roles and "music" in roles and spec.duck_music_under_voice),
        "mastered": bool(spec.master and capabilities().has_filter("loudnorm")),
        "size_bytes": info.size_bytes,
    }


def measure_loudness(path: str) -> Dict[str, Any]:
    """Read integrated loudness back from the rendered file (QC evidence)."""
    if not capabilities().has_filter("ebur128"):
        return {"available": False}
    try:
        stderr = run_ffmpeg(
            ["-i", path, "-filter_complex", "ebur128=peak=true", "-f", "null", "-"],
            label="audio:ebur128", timeout=300,
        )
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": str(exc)[:200]}
    summary: Dict[str, Any] = {"available": True}
    tail = stderr[-2500:]
    for key, label in (("integrated_lufs", "I:"), ("loudness_range", "LRA:"), ("true_peak_dbfs", "Peak:")):
        marker = tail.rfind(label)
        if marker != -1:
            fragment = tail[marker + len(label):].strip().split()
            if fragment:
                try:
                    summary[key] = float(fragment[0])
                except ValueError:
                    pass
    return summary


def attach_audio(video_path: str, audio_path: Optional[str], out_path: str,
                 *, duration_sec: Optional[float] = None) -> Dict[str, Any]:
    """Mux a finished audio bed onto a finished picture without re-encoding video."""
    ensure_parent(out_path)
    args: List[str] = ["-i", video_path]
    if audio_path and Path(audio_path).exists():
        args += ["-i", audio_path, "-map", "0:v:0", "-map", "1:a:0"]
    else:
        args += ["-map", "0:v:0", "-an"]
    args += ["-c:v", "copy"]
    if audio_path and Path(audio_path).exists():
        args += ["-c:a", "aac", "-b:a", "192k", "-ar", str(OUT_SAMPLE_RATE), "-ac", "2"]
    if duration_sec:
        args += ["-t", f"{duration_sec:.3f}"]
    args += ["-shortest", "-movflags", "+faststart", out_path]
    run_ffmpeg(args, label="audio:attach", timeout=600)
    info = probe_media(out_path)
    return {"path": out_path, "duration_sec": info.duration_sec, "has_audio": info.has_audio,
            "size_bytes": info.size_bytes}


def strip_audio(video_path: str, out_path: str) -> str:
    ensure_parent(out_path)
    run_ffmpeg(["-i", video_path, "-c:v", "copy", "-an", out_path], label="audio:strip", timeout=300)
    return out_path


def extract_audio(video_path: str, out_path: str) -> Optional[str]:
    info = probe_media(video_path)
    if not info.has_audio:
        return None
    ensure_parent(out_path)
    run_ffmpeg(["-i", video_path, "-vn", "-c:a", "aac", "-b:a", "192k", out_path],
               label="audio:extract", timeout=300)
    return out_path
