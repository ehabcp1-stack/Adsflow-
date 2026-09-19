"""Assembly & Editing Engine.

Timeline Builder · Voice Sync · Music · SFX · Transitions · Arabic Caption
Engine · Brand Layer · Motion Graphics · Color & Look · Audio Mastering ·
Final Render.

Arabic captions are rendered by OUR editor — never drawn by a video model.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.enums import EditingStyle, JobType, ProjectState
from app.core.errors import NotFound
from app.models import BrandKit, GenerationJob, Project, Render, Scene, ScriptVersion, Storyboard
from app.media.assemble import AssemblySpec, assemble_reel, make_thumbnail
from app.media.captions import CaptionStyle, style_for_template
from app.media.ffmpeg import render_enabled
from app.media.overlays import BrandLayer
from app.services import approvals as approval_service
from app.services import media_bridge
from app.services.media_placeholder import concat_clips, save_clip, save_frame
from app.services.storage import get_storage
from app.services.storyboards import active_storyboard

EDITING_STYLES: List[Dict[str, Any]] = [
    {
        "key": EditingStyle.LUXURY_CLEAN.value,
        "label_en": "Luxury Clean",
        "label_ar": "فخم نظيف",
        "cut_pace_sec": 4.0,
        "transition": "soft_dissolve",
        "caption_density": "low",
        "color_look": "cool_contrast",
        "music_energy": 0.35,
    },
    {
        "key": EditingStyle.FAST_SOCIAL.value,
        "label_en": "Fast Social",
        "label_ar": "سريع سوشيال",
        "cut_pace_sec": 1.8,
        "transition": "whip_pan",
        "caption_density": "high",
        "color_look": "punchy",
        "music_energy": 0.85,
    },
    {
        "key": EditingStyle.EMOTIONAL_CINEMATIC.value,
        "label_en": "Emotional Cinematic",
        "label_ar": "سينمائي عاطفي",
        "cut_pace_sec": 3.6,
        "transition": "match_cut",
        "caption_density": "medium",
        "color_look": "warm_film",
        "music_energy": 0.5,
    },
    {
        "key": EditingStyle.DIRECT_SALES.value,
        "label_en": "Direct Sales",
        "label_ar": "بيع مباشر",
        "cut_pace_sec": 2.2,
        "transition": "cut",
        "caption_density": "high",
        "color_look": "neutral_bright",
        "music_energy": 0.7,
    },
    {
        "key": EditingStyle.MINIMAL_PREMIUM.value,
        "label_en": "Minimal Premium",
        "label_ar": "بسيط راقي",
        "cut_pace_sec": 4.5,
        "transition": "cut",
        "caption_density": "low",
        "color_look": "muted_elegant",
        "music_energy": 0.3,
    },
]

DEFAULT_EDIT_SETTINGS: Dict[str, Any] = {
    "captions_enabled": True,
    "caption_template": "bold_bar",
    "music_enabled": True,
    "music_volume": 0.22,
    "voice_volume": 1.0,
    "duck_music_under_voice": True,
    "sfx_enabled": True,
    "branding_enabled": True,
    "logo_position": "top_left",
    "cta_enabled": True,
    "end_screen_enabled": True,
    "color_look": "warm_film",
}

CAPTION_TEMPLATES = [
    {"key": "bold_bar", "label_en": "Bold Bar", "label_ar": "شريط عريض"},
    {"key": "clean_line", "label_en": "Clean Line", "label_ar": "سطر نظيف"},
    {"key": "word_highlight", "label_en": "Word Highlight", "label_ar": "تمييز كلمة"},
]


def style_config(key: str) -> Dict[str, Any]:
    return next((s for s in EDITING_STYLES if s["key"] == key), EDITING_STYLES[0])


def recommend_style(project: Project, concept_angle: Optional[str] = None) -> str:
    mapping = {
        "luxury": EditingStyle.LUXURY_CLEAN.value,
        "emotional": EditingStyle.EMOTIONAL_CINEMATIC.value,
        "direct_response": EditingStyle.DIRECT_SALES.value,
        "information_offer": EditingStyle.DIRECT_SALES.value,
        "ugc_like": EditingStyle.FAST_SOCIAL.value,
        "lifestyle": EditingStyle.FAST_SOCIAL.value,
        "investment": EditingStyle.MINIMAL_PREMIUM.value,
        "authority_trust": EditingStyle.MINIMAL_PREMIUM.value,
    }
    if concept_angle in mapping:
        return mapping[concept_angle]
    return EditingStyle.LUXURY_CLEAN.value if project.tone == "luxury" else EditingStyle.EMOTIONAL_CINEMATIC.value


# --------------------------------------------------------------------------
# Arabic Caption Engine
# --------------------------------------------------------------------------
MAX_CHARS_PER_LINE = 26
MAX_LINES = 2
SAFE_ZONE = {"top_pct": 12, "bottom_pct": 18, "side_pct": 8}


def build_captions(script: ScriptVersion, *, density: str = "medium", template: str = "bold_bar") -> List[Dict[str, Any]]:
    """RTL-aware caption track. Splitting respects Arabic word boundaries."""
    captions: List[Dict[str, Any]] = []
    for line in script.lines or []:
        text = (line.get("on_screen_text") or line.get("voice_line") or "").strip()
        if not text:
            continue
        words = text.split()
        chunks: List[str] = []
        current = ""
        limit = MAX_CHARS_PER_LINE if density != "high" else 18
        for word in words:
            if len(current) + len(word) + 1 <= limit:
                current = f"{current} {word}".strip()
            else:
                chunks.append(current)
                current = word
        if current:
            chunks.append(current)
        chunks = chunks[: MAX_LINES if density == "low" else 4]

        start, end = float(line.get("start", 0)), float(line.get("end", 0))
        span = max((end - start) / max(len(chunks), 1), 0.6)
        for i, chunk in enumerate(chunks):
            captions.append(
                {
                    "text": chunk,
                    "start": round(start + i * span, 2),
                    "end": round(min(start + (i + 1) * span, end), 2),
                    "direction": "rtl",
                    "align": "center",
                    "lines": 1,
                    "template": template,
                    "safe_zone": SAFE_ZONE,
                    "highlight_word": chunk.split()[0] if template == "word_highlight" and chunk.split() else None,
                }
            )
    return captions


# --------------------------------------------------------------------------
# Timeline Builder
# --------------------------------------------------------------------------
def build_timeline(db: Session, project: Project, storyboard: Storyboard, script: Optional[ScriptVersion]) -> List[Dict[str, Any]]:
    settings_ = {**DEFAULT_EDIT_SETTINGS, **(project.edit_settings or {})}
    style = style_config(project.editing_style)
    brand = db.get(BrandKit, project.brand_kit_id) if project.brand_kit_id else None

    voice_job = (
        db.query(GenerationJob)
        .filter(GenerationJob.project_id == project.id, GenerationJob.job_type == JobType.VOICE_GENERATION.value)
        .order_by(GenerationJob.created_at.desc())
        .first()
    )
    music_job = (
        db.query(GenerationJob)
        .filter(GenerationJob.project_id == project.id, GenerationJob.job_type == JobType.MUSIC_GENERATION.value)
        .order_by(GenerationJob.created_at.desc())
        .first()
    )

    tracks: List[Dict[str, Any]] = []
    video_clips = []
    for scene in sorted(storyboard.scenes, key=lambda s: s.scene_number):
        video_clips.append(
            {
                "scene_id": scene.id,
                "scene_number": scene.scene_number,
                "start": scene.start_time,
                "end": scene.end_time,
                "url": scene.output_url or scene.thumbnail_url,
                "poster": scene.thumbnail_url,
                "transition": style["transition"] if scene.scene_number > 1 else "none",
                "method": scene.production_method,
                "color_look": style["color_look"],
                "on_screen_text": scene.on_screen_text,
            }
        )
    tracks.append({"type": "video", "clips": video_clips})

    if project.voice_over_enabled:
        tracks.append(
            {
                "type": "voice",
                "url": (voice_job.result or {}).get("url") if voice_job else None,
                "volume": settings_["voice_volume"],
                "clips": [
                    {"start": line.get("start"), "end": line.get("end"), "text": line.get("voice_line")}
                    for line in (script.lines if script else [])
                ],
            }
        )
    if settings_["music_enabled"]:
        tracks.append(
            {
                "type": "music",
                "url": (music_job.result or {}).get("url") if music_job else None,
                "volume": settings_["music_volume"],
                "energy": style["music_energy"],
                "ducking": settings_["duck_music_under_voice"],
            }
        )
    if settings_["sfx_enabled"]:
        tracks.append(
            {
                "type": "sfx",
                "clips": [
                    {"start": s.start_time, "cue": s.sfx_instruction}
                    for s in storyboard.scenes
                    if s.sfx_instruction and s.sfx_instruction != "بدون مؤثرات"
                ],
            }
        )
    if settings_["captions_enabled"] and script:
        tracks.append(
            {
                "type": "captions",
                "template": settings_["caption_template"],
                "font": brand.font_arabic if brand else "Cairo",
                "color": brand.primary_color if brand else "#FFFFFF",
                "clips": build_captions(script, density=style["caption_density"], template=settings_["caption_template"]),
            }
        )
    if settings_["branding_enabled"]:
        tracks.append(
            {
                "type": "brand",
                "logo_url": brand.logo_url if brand else None,
                "position": settings_["logo_position"],
                "primary_color": brand.primary_color if brand else "#0F172A",
                "secondary_color": brand.secondary_color if brand else "#2563EB",
            }
        )
    if settings_["cta_enabled"]:
        tracks.append(
            {
                "type": "cta",
                "text": project.cta,
                "phone": brand.phone if brand else None,
                "start": max(storyboard.total_duration_sec - 5, 0),
                "end": storyboard.total_duration_sec,
            }
        )
    if settings_["end_screen_enabled"]:
        tracks.append(
            {
                "type": "end_screen",
                "template": (brand.end_screen_template if brand else {}) or {"style": "logo_center"},
                "start": max(storyboard.total_duration_sec - 3, 0),
                "end": storyboard.total_duration_sec,
            }
        )
    return tracks


def _brand_layer(db: Session, project: Project) -> BrandLayer:
    """Translate the project's Brand Kit into what the renderer needs.

    The customer's brand is rendered — never AdFlow AI's or TADAFQ's.
    """
    brand = db.get(BrandKit, project.brand_kit_id) if project.brand_kit_id else None
    template = (brand.end_screen_template if brand else {}) or {}
    cta_template = (brand.cta_template if brand else {}) or {}
    settings_ = {**DEFAULT_EDIT_SETTINGS, **(project.edit_settings or {})}
    return BrandLayer(
        name=(brand.name_ar or brand.name) if brand else project.name,
        logo_path=media_bridge.local_path_for(brand.logo_url) if brand and brand.logo_url else None,
        primary_color=brand.primary_color if brand else "#0F172A",
        secondary_color=brand.secondary_color if brand else "#2563EB",
        accent_color=brand.accent_color if brand else "#1D4ED8",
        font_arabic=brand.font_arabic if brand else None,
        font_latin=brand.font_latin if brand else None,
        phone=brand.phone if brand else None,
        website=brand.website if brand else None,
        social_handle=(brand.social_handles or {}).get("instagram") if brand else None,
        cta_text=project.cta or cta_template.get("text", ""),
        tagline=template.get("tagline", "") or (brand.name_ar if brand else ""),
        end_screen_template=template,
        logo_position=settings_.get("logo_position", "top_left"),
    )


def _assembly_captions(
    script: Optional[ScriptVersion], voice_cues: Optional[List[Dict[str, Any]]] = None
) -> List[Dict[str, Any]]:
    """Caption cards for the render.

    Preferred source is the voice: cues timed against the audio that actually
    exists cannot drift from it. The script's planned line timings are the
    fallback for a project with captions but no voice-over, and they drift by
    exactly the difference between the estimate and the take.

    The on-screen wording may deliberately differ from the spoken line — the
    dialect engine shortens spoken filler for the screen — so a script line
    still wins on *wording* where one is available.
    """
    if voice_cues:
        captions: List[Dict[str, Any]] = []
        for cue in voice_cues:
            text = (cue.get("text") or "").strip()
            if not text:
                continue
            words = cue.get("words") or []
            captions.append({
                "text": text,
                "start": float(cue.get("start", 0.0)),
                "end": float(cue.get("end", 0.0)),
                # The longest word carries the emphasis: it is the one the eye
                # lands on, and it is almost always the content word.
                "highlight_word": max((w.get("word", "") for w in words), key=len, default=None),
                "words": words,
                "timing_source": cue.get("source", "estimated"),
            })
        if captions:
            return captions

    captions = []
    for line in (script.lines if script else []) or []:
        text = (line.get("on_screen_text") or line.get("voice_line") or "").strip()
        if not text:
            continue
        captions.append({
            "text": text,
            "start": float(line.get("start", 0.0) or 0.0),
            "end": float(line.get("end", 0.0) or 0.0),
            "highlight_word": line.get("highlight_word"),
            "timing_source": "planned",
        })
    return captions


def _voice_caption_cues(db: Session, project: Project) -> Optional[List[Dict[str, Any]]]:
    """Caption cues produced by the voice job, if that job has run."""
    job = (
        db.query(GenerationJob)
        .filter(
            GenerationJob.project_id == project.id,
            GenerationJob.job_type == JobType.VOICE_GENERATION.value,
        )
        .order_by(GenerationJob.created_at.desc())
        .first()
    )
    return ((job.result or {}).get("caption_cues") if job else None) or None


def _job_media(db: Session, project: Project, job_type: str) -> Optional[str]:
    job = (
        db.query(GenerationJob)
        .filter(GenerationJob.project_id == project.id, GenerationJob.job_type == job_type)
        .order_by(GenerationJob.created_at.desc())
        .first()
    )
    url = (job.result or {}).get("url") if job else None
    return media_bridge.local_path_for(url)


def _scene_clip_paths(db: Session, storyboard: Storyboard) -> List[str]:
    paths: List[str] = []
    for scene in sorted(storyboard.scenes, key=lambda s: s.scene_number):
        local = media_bridge.local_path_for(scene.output_url)
        if local and local.lower().endswith((".mp4", ".mov", ".m4v")):
            paths.append(local)
    return paths


def assembly_spec_for(
    db: Session,
    project: Project,
    *,
    overrides: Optional[Dict[str, Any]] = None,
) -> Optional[AssemblySpec]:
    """Build the renderer spec for this project, with optional overrides.

    Export variants ("without captions", "clean, no logo", ...) are produced by
    re-assembling with the relevant layer switched off rather than by faking a
    file, so what the customer downloads is genuinely that version.
    Returns None when there is nothing real to assemble.
    """
    storyboard = active_storyboard(db, project)
    if not storyboard:
        return None
    clip_paths = _scene_clip_paths(db, storyboard)
    if not clip_paths or not render_enabled():
        return None
    script = db.get(ScriptVersion, storyboard.script_version_id) if storyboard.script_version_id else None
    settings_ = {**DEFAULT_EDIT_SETTINGS, **(project.edit_settings or {}), **(overrides or {})}
    brand = _brand_layer(db, project)
    caption_style = style_for_template(
        settings_.get("caption_template", "bold_bar"),
        font_family=brand.font_arabic,
        latin_font_family=brand.font_latin,
        accent_color=brand.secondary_color,
    )
    return AssemblySpec(
        scene_clips=clip_paths,
        captions=_assembly_captions(script, _voice_caption_cues(db, project)),
        caption_style=caption_style,
        captions_enabled=bool(settings_.get("captions_enabled", True)),
        brand=brand,
        branding_enabled=bool(settings_.get("branding_enabled", True)),
        cta_enabled=bool(settings_.get("cta_enabled", True)),
        cta_text=project.cta or "",
        end_screen_enabled=bool(settings_.get("end_screen_enabled", True)),
        platform=project.platform,
        voice_path=_job_media(db, project, JobType.VOICE_GENERATION.value)
        if (project.voice_over_enabled and settings_.get("voice_enabled", True)) else None,
        music_path=_job_media(db, project, JobType.MUSIC_GENERATION.value)
        if settings_.get("music_enabled", True) else None,
        voice_volume=float(settings_.get("voice_volume", 1.0)),
        music_volume=float(settings_.get("music_volume", 0.22)),
        duck_music_under_voice=bool(settings_.get("duck_music_under_voice", True)),
    )


def render_project(db: Session, project: Project, *, user_id: Optional[str] = None) -> Render:
    """Assemble the finished reel.

    Where real scene clips exist this produces an actual 1080x1920 MP4 with
    burnt-in Arabic captions, the brand layer, the CTA, an end screen and a
    mixed, ducked, loudness-normalised audio bed. Where they do not (mock run
    with no source media) it falls back to the deterministic placeholder reel
    and says so on the Render row, so the UI never implies more than happened.
    """
    storyboard = active_storyboard(db, project)
    if not storyboard:
        raise NotFound("Nothing to edit yet.", "ما أكو شي للمونتاج.")
    script = db.get(ScriptVersion, storyboard.script_version_id) if storyboard.script_version_id else None

    timeline = build_timeline(db, project, storyboard, script)
    settings_ = {**DEFAULT_EDIT_SETTINGS, **(project.edit_settings or {})}
    style = style_config(project.editing_style)
    last = db.query(Render).filter(Render.project_id == project.id).order_by(Render.version.desc()).first()
    version = (last.version + 1) if last else 1
    for render in project.renders:
        render.is_active = False

    clip_paths = _scene_clip_paths(db, storyboard)
    brand = _brand_layer(db, project)
    report: Dict[str, Any] = {}
    url: Optional[str] = None
    poster: Optional[str] = None
    duration = storyboard.total_duration_sec
    width, height = 1080, 1920

    spec = assembly_spec_for(db, project)
    if spec:
        key = f"projects/{project.id}/renders/v{version}/master.mp4"
        try:
            record = media_bridge.render_to_storage(
                key, lambda target: assemble_reel(spec, target)
            )
            report = {k: v for k, v in record.items() if k not in ("path", "key")}
            url = record["url"]
            duration = record.get("duration_sec") or duration
            width = record.get("width") or width
            height = record.get("height") or height
            poster_key = f"projects/{project.id}/renders/v{version}/poster.png"
            poster = media_bridge.render_to_storage(
                poster_key,
                lambda target: {"ok": bool(make_thumbnail(record["path"], target, at_sec=1.2))},
            )["url"]
        except Exception as exc:  # noqa: BLE001 - surfaced on the Render row
            report = {"error": str(exc)[:500], "stage": "assembly"}
            url = None

    if not url:
        # Honest fallback: a deterministic placeholder reel, labelled as one.
        poster = poster or save_frame(
            f"projects/{project.id}/renders/v{version}/poster.svg",
            seed=f"{project.id}-render-{version}",
            title_ar=project.name,
            subtitle=f"{project.duration_sec}s · 1080x1920",
            badge=f"RENDER V{version}",
        )
        url = concat_clips(f"projects/{project.id}/renders/v{version}/master.mp4", clip_paths)
        if not url:
            url = save_clip(
                f"projects/{project.id}/renders/v{version}/master.mp4",
                seed=f"{project.id}-{version}",
                duration_sec=storyboard.total_duration_sec,
                label=project.name,
                width=540, height=960,
            )
        report.setdefault("placeholder", True)
        # Two very different failures land here, and saying the wrong one costs
        # hours. "No clips" means production never produced anything to join;
        # an assembly error means the clips were there and the renderer died on
        # them — the live one was `assemble:overlays failed (exit -9)`, FFmpeg
        # killed part-way through burning the overlays. The old note claimed
        # there were no clips in both cases, which sends the reader back to
        # production to look for a problem that is not there.
        report.setdefault(
            "note",
            f"Placeholder reel: assembly failed at {report['stage']} — {report['error']}"
            if report.get("error")
            else "Placeholder reel: no real scene clips were available to assemble.",
        )

    render = Render(
        project_id=project.id,
        version=version,
        editing_style=project.editing_style,
        settings={**settings_, "color_look": style["color_look"], "render_report": report},
        timeline=timeline,
        url=url,
        poster_url=poster,
        duration_sec=duration,
        width=width,
        height=height,
        status="completed",
        is_active=True,
    )
    db.add(render)
    project.thumbnail_url = project.thumbnail_url or poster
    if project.state == ProjectState.GENERATING.value:
        approval_service.set_state(db, project, ProjectState.EDITING, note="assembled")
    db.flush()
    return render


def active_render(db: Session, project: Project) -> Optional[Render]:
    return (
        db.query(Render)
        .filter(Render.project_id == project.id, Render.is_active.is_(True))
        .order_by(Render.version.desc())
        .first()
    )


def update_edit_settings(db: Session, project: Project, changes: Dict[str, Any]) -> Project:
    merged = {**DEFAULT_EDIT_SETTINGS, **(project.edit_settings or {}), **changes}
    project.edit_settings = merged
    if "editing_style" in changes:
        project.editing_style = changes["editing_style"]
    db.flush()
    return project


def render_payload(render: Render) -> Dict[str, Any]:
    return {
        "id": render.id,
        "version": render.version,
        "editing_style": render.editing_style,
        "settings": render.settings,
        "timeline": render.timeline,
        "url": render.url,
        "poster_url": render.poster_url,
        "duration_sec": render.duration_sec,
        "width": render.width,
        "height": render.height,
        "status": render.status,
    }


# --------------------------------------------------------------------------
# Existing Video Remix
# --------------------------------------------------------------------------
REMIX_OPERATIONS = [
    {"key": "keep", "label_en": "Keep", "label_ar": "احتفظ"},
    {"key": "trim", "label_en": "Trim", "label_ar": "قص"},
    {"key": "reorder", "label_en": "Reorder", "label_ar": "إعادة ترتيب"},
    {"key": "speed", "label_en": "Speed", "label_ar": "سرعة"},
    {"key": "reframe", "label_en": "Reframe 9:16", "label_ar": "إعادة تأطير ٩:١٦"},
    {"key": "crop", "label_en": "Crop", "label_ar": "اقتصاص"},
    {"key": "color_grade", "label_en": "Color Grade", "label_ar": "تدرج لوني"},
    {"key": "stabilize", "label_en": "Stabilize", "label_ar": "تثبيت"},
    {"key": "remove_audio", "label_en": "Remove Original Audio", "label_ar": "حذف الصوت الأصلي"},
    {"key": "add_voice", "label_en": "Add New Voice Over", "label_ar": "إضافة تعليق صوتي"},
    {"key": "add_captions", "label_en": "Add Captions", "label_ar": "إضافة كابشن"},
    {"key": "add_branding", "label_en": "Add Branding", "label_ar": "إضافة الهوية"},
    {"key": "add_music", "label_en": "Add Music", "label_ar": "إضافة موسيقى"},
    {"key": "add_sfx", "label_en": "Add SFX", "label_ar": "إضافة مؤثرات"},
    {"key": "ai_enhance", "label_en": "AI Enhance", "label_ar": "تحسين بالذكاء"},
    {"key": "video_to_video", "label_en": "Video-to-Video", "label_ar": "تحويل فيديو لفيديو"},
]


def default_remix_plan(segments: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Turn analyzed video segments into a re-production plan."""
    keep = [s for s in segments if s.get("strength") in ("strong", "usable")]
    return {
        "operations": ["trim", "reorder", "reframe", "remove_audio", "add_voice", "add_captions", "add_branding", "add_music"],
        "segments": [
            {"start": s["start"], "end": s["end"], "op": "keep", "score": s.get("score")} for s in keep
        ],
        "notes_ar": "نستخدم المقاطع القوية فقط، نعيد التأطير عمودي، نحذف الصوت الأصلي ونركّب تعليق عراقي جديد.",
    }
