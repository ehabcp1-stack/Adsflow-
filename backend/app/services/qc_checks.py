"""Deterministic QC — checks run against the actual rendered file.

An AI opinion about a video is useful; it is not evidence. Before any model is
asked what it thinks, AdFlow AI verifies the things that are simply true or
false about the file it just produced: does it exist, is it the right size and
length, does it have an audio track, is the loudness sane, did the captions and
the CTA actually get drawn, and does the copy carry the customer's real phone
number and project name.

These checks are what make the "critical error overrides the score" rule
meaningful — a reel with the wrong phone number fails regardless of how good a
model thinks it looks.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.media.probe import probe_media
from app.models import BrandKit, Project, Render, ScriptVersion, Storyboard
from app.services import media_bridge

log = logging.getLogger("adflow.qc_checks")

TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
#: Social platforms normalise around -14 LUFS; well outside this and the ad
#: will either be turned down hard or sound weak next to everything else.
LOUDNESS_MIN = -20.0
LOUDNESS_MAX = -9.0
#: How far the render may drift from the approved storyboard length.
DURATION_TOLERANCE_SEC = 4.0

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def normalize_digits(text: str) -> str:
    """Arabic-Indic and Western digits must compare equal — ٠٧٧٠ is 0770."""
    return (text or "").translate(_DIGITS)


def digits_only(text: str) -> str:
    return re.sub(r"\D", "", normalize_digits(text))


def _check(code: str, passed: bool, severity: str, en: str, ar: str,
           **extra: Any) -> Dict[str, Any]:
    return {"code": code, "passed": passed,
            "severity": "info" if passed else severity,
            "message_en": en, "message_ar": ar, **extra}


def file_checks(render: Render, *, expected_duration: Optional[float] = None) -> List[Dict[str, Any]]:
    """Everything that can be read straight off the rendered file."""
    checks: List[Dict[str, Any]] = []
    path = media_bridge.local_path_for(render.url)
    if not path or not Path(path).exists():
        return [_check("output_missing", False, "critical",
                       "The rendered file could not be found in storage.",
                       "ملف المونتاج مو موجود بالتخزين.")]

    info = probe_media(path)
    checks.append(_check(
        "output_exists", bool(info.ok), "critical",
        "Rendered file is readable.", "ملف المونتاج يفتح بشكل سليم.",
        detail=info.error,
    ))
    if not info.ok:
        return checks

    is_video = info.kind == "video"
    checks.append(_check(
        "container_is_video", is_video, "critical",
        "Output is a real video file.", "المخرج فيديو حقيقي.",
        detail=info.kind,
    ))
    checks.append(_check(
        "resolution_1080x1920", info.width == TARGET_WIDTH and info.height == TARGET_HEIGHT,
        "critical" if is_video else "warning",
        f"Frame size is {info.width}x{info.height}; the deliverable must be {TARGET_WIDTH}x{TARGET_HEIGHT}.",
        f"مقاس الفيديو {info.width}x{info.height} والمفروض يكون {TARGET_WIDTH}x{TARGET_HEIGHT}.",
        width=info.width, height=info.height,
    ))
    checks.append(_check(
        "codec_h264", (info.video_codec or "").lower() in {"h264", "avc1"}, "warning",
        f"Video codec is {info.video_codec}; H.264 is the safe choice for every platform.",
        f"ترميز الفيديو {info.video_codec}؛ H.264 هو الأأمن لكل المنصات.",
        codec=info.video_codec,
    ))
    checks.append(_check(
        "has_audio_track", bool(info.has_audio), "critical",
        "The reel has an audio track.", "الريل بيه مسار صوتي.",
    ))
    if expected_duration:
        drift = abs((info.duration_sec or 0) - expected_duration)
        checks.append(_check(
            "duration_matches_plan", drift <= DURATION_TOLERANCE_SEC, "warning",
            f"Rendered {info.duration_sec:.1f}s against an approved {expected_duration:.1f}s plan.",
            f"المدة الناتجة {info.duration_sec:.1f} ثانية مقابل خطة معتمدة {expected_duration:.1f} ثانية.",
            rendered_sec=info.duration_sec, planned_sec=expected_duration,
        ))
    checks.append(_check(
        "file_not_empty", (info.size_bytes or 0) > 50_000, "critical",
        "Rendered file has real content.", "حجم الملف منطقي ومو فارغ.",
        size_bytes=info.size_bytes,
    ))
    return checks


def audio_checks(render: Render) -> List[Dict[str, Any]]:
    report = (render.settings or {}).get("render_report") or {}
    loudness = report.get("loudness") or {}
    integrated = loudness.get("integrated_lufs")
    checks: List[Dict[str, Any]] = []
    if integrated is None:
        checks.append(_check("loudness_measured", False, "warning",
                             "Loudness was not measured for this render.",
                             "ما انقاست شدة الصوت لهذا المونتاج."))
        return checks
    checks.append(_check(
        "loudness_in_range", LOUDNESS_MIN <= integrated <= LOUDNESS_MAX, "warning",
        f"Integrated loudness {integrated:.1f} LUFS (target about -14).",
        f"مستوى الصوت {integrated:.1f} LUFS (المستهدف تقريباً -14).",
        integrated_lufs=integrated,
    ))
    audio_stage = (report.get("stages") or {}).get("audio") or {}
    if audio_stage.get("sources"):
        checks.append(_check(
            "music_ducked_under_voice",
            bool(audio_stage.get("ducked")) or "music" not in audio_stage.get("sources", []),
            "warning",
            "Music ducks under the voice-over.", "الموسيقى تنخفض تحت التعليق الصوتي.",
        ))
    return checks


def overlay_checks(render: Render, *, captions_expected: int = 0,
                   branding_expected: bool = True, cta_expected: bool = True) -> List[Dict[str, Any]]:
    """Confirm the layers the settings asked for were really drawn."""
    report = (render.settings or {}).get("render_report") or {}
    overlays = (report.get("stages") or {}).get("overlays") or {}
    captions = overlays.get("captions") or []
    checks: List[Dict[str, Any]] = []

    if captions_expected:
        checks.append(_check(
            "captions_rendered", len(captions) > 0, "critical",
            f"{len(captions)} caption(s) burnt into the picture.",
            f"انرسمت {len(captions)} كابشن بالفيديو.",
            rendered=len(captions), expected=captions_expected,
        ))
        outside = [c for c in captions if not c.get("within_safe_zone", True)]
        checks.append(_check(
            "captions_in_safe_zone", not outside, "warning",
            "Every caption stays inside the platform safe zone.",
            "كل الكابشن داخل المنطقة الآمنة للمنصة.",
            offenders=len(outside),
        ))
        not_rtl = [c for c in captions if c.get("rtl") is False]
        checks.append(_check(
            "arabic_captions_rtl", not not_rtl, "critical",
            "Arabic captions were laid out right-to-left.",
            "الكابشن العربي انكتب من اليمين لليسار بشكل صحيح.",
            offenders=len(not_rtl),
        ))
    if branding_expected:
        checks.append(_check(
            "brand_layer_present", bool(overlays.get("logo")), "warning",
            "Brand logo is on screen.", "شعار العلامة ظاهر بالفيديو.",
        ))
    if cta_expected:
        checks.append(_check(
            "cta_present", bool(overlays.get("cta")), "critical",
            "A call-to-action card is on screen.", "أكو كارت دعوة للتواصل بالفيديو.",
        ))
        checks.append(_check(
            "end_screen_present", bool(overlays.get("end_screen")), "warning",
            "The reel closes on a branded end screen.",
            "الريل يختم بشاشة نهاية بالهوية.",
        ))
    return checks


def copy_checks(project: Project, script: Optional[ScriptVersion],
                brand: Optional[BrandKit]) -> List[Dict[str, Any]]:
    """Facts about the words: the phone and the project name must be right."""
    spoken = (script.voice_over_text if script else "") or ""
    on_screen = " ".join(
        item.get("text", "") for item in ((script.on_screen_text if script else []) or [])
    )
    line_text = " ".join(
        f"{line.get('voice_line', '')} {line.get('on_screen_text', '')}"
        for line in ((script.lines if script else []) or [])
    )
    corpus = " ".join([spoken, on_screen, line_text, project.cta or "", project.key_information or ""])
    checks: List[Dict[str, Any]] = []

    if brand and brand.phone:
        wanted = digits_only(brand.phone)
        present = bool(wanted) and wanted in digits_only(corpus)
        checks.append(_check(
            "phone_matches_brand_kit", present, "critical",
            "The phone number in the ad matches the Brand Kit.",
            "رقم الهاتف بالإعلان يطابق رقم هوية العلامة.",
            expected=brand.phone,
        ))
    if project.name:
        checks.append(_check(
            "project_name_present", project.name.strip() in corpus, "warning",
            "The project name is spoken or shown.",
            "اسم المشروع ينذكر أو يظهر.",
            expected=project.name,
        ))
    checks.append(_check(
        "cta_in_copy", bool((project.cta or "").strip()) and (project.cta.strip() in corpus),
        "critical",
        "The call to action appears in the approved copy.",
        "الدعوة للتواصل موجودة بالنص المعتمد.",
    ))
    return checks


def run_deterministic_checks(
    db: Session,
    project: Project,
    render: Render,
    *,
    script: Optional[ScriptVersion] = None,
    brand: Optional[BrandKit] = None,
    storyboard: Optional[Storyboard] = None,
) -> Dict[str, Any]:
    """Everything measurable, in one place, with a pass/fail summary."""
    settings_ = render.settings or {}
    captions_expected = len((script.lines if script else []) or [])
    checks: List[Dict[str, Any]] = []
    checks += file_checks(render, expected_duration=storyboard.total_duration_sec if storyboard else None)
    checks += audio_checks(render)
    checks += overlay_checks(
        render,
        captions_expected=captions_expected if settings_.get("captions_enabled", True) else 0,
        branding_expected=bool(settings_.get("branding_enabled", True)),
        cta_expected=bool(settings_.get("cta_enabled", True)),
    )
    checks += copy_checks(project, script, brand)

    failures = [c for c in checks if not c["passed"]]
    criticals = [c for c in failures if c["severity"] == "critical"]
    placeholder = bool((settings_.get("render_report") or {}).get("placeholder"))
    return {
        "checks": checks,
        "passed": len(checks) - len(failures),
        "total": len(checks),
        "failures": failures,
        "critical_failures": criticals,
        "all_passed": not failures,
        "placeholder_render": placeholder,
    }


#: Deterministic failure codes that map onto the product's critical-error list.
CRITICAL_CODE_MAP = {
    "output_missing": "product_distortion",
    "container_is_video": "product_distortion",
    "resolution_1080x1920": "product_distortion",
    "has_audio_track": "missing_audio",
    "captions_rendered": "arabic_error",
    "arabic_captions_rtl": "arabic_error",
    "cta_present": "missing_cta",
    "cta_in_copy": "missing_cta",
    "phone_matches_brand_kit": "wrong_phone_number",
    "file_not_empty": "product_distortion",
}
