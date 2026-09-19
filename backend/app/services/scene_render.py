"""Render one storyboard scene into a real vertical clip.

This is where the product's central economic claim is cashed: a scene whose
source is the customer's own photo or footage is produced locally with FFmpeg
for the cost of CPU time, and only a scene that genuinely needs generation
reaches a paid provider.

Method -> what actually happens
------------------------------
original_video   real trim / reframe / grade of the uploaded clip
original_photo   the photo held with a barely-there move (no slideshow feel)
photo_motion     the photo animated with a chosen cinematic move
motion_graphics  a designed offer/info card, animated
ai_image         provider image -> animated like a photo
ai_video         provider video -> normalised to 1080x1920

Everything returns a normalised clip (1080x1920, 30fps, AAC track) so the
assembler never has to reconcile mismatched inputs.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.enums import ProductionMethod
from app.media.assemble import make_thumbnail
from app.media.ffmpeg import OUT_HEIGHT, OUT_WIDTH, render_enabled
from app.media.motion import MOTION_PRESETS, recommend_motion, render_photo_motion
from app.media.motion_graphics import render_offer_scene
from app.media.probe import probe_media
from app.media.remix import RemixOp, apply_remix, op_from_dict
from app.models import Asset, BrandKit, Project, Scene
from app.services import media_bridge
from app.services.media_placeholder import save_clip, save_frame

log = logging.getLogger("adflow.scene_render")

#: Methods produced entirely on our own machines — no provider, no spend.
LOCAL_METHODS = {
    ProductionMethod.ORIGINAL_VIDEO.value,
    ProductionMethod.ORIGINAL_PHOTO.value,
    ProductionMethod.PHOTO_MOTION.value,
    ProductionMethod.MOTION_GRAPHICS.value,
}


def scene_duration(scene: Scene) -> float:
    return max(float(scene.end_time) - float(scene.start_time), 1.2)


def _scene_asset(db: Session, scene: Scene) -> Optional[Asset]:
    if not scene.selected_asset_id:
        return None
    return db.get(Asset, scene.selected_asset_id)


def _asset_local_path(asset: Optional[Asset]) -> Optional[str]:
    if not asset:
        return None
    return media_bridge.local_path_for(asset.url or asset.storage_key)


def _look_for(project: Project) -> str:
    from app.services.editing import style_config

    return style_config(project.editing_style).get("color_look", "neutral")


def _offer_text(scene: Scene, project: Project) -> Dict[str, Any]:
    """Compose the copy for a motion-graphics scene from what the scene says."""
    headline = (scene.on_screen_text or scene.voice_line or project.cta or project.name).strip()
    lines: List[str] = []
    if scene.voice_line and scene.voice_line.strip() != headline:
        lines.append(scene.voice_line.strip())
    info = (project.key_information or "").strip()
    if info and len(lines) < 2:
        lines.extend([part.strip() for part in info.split("،") if part.strip()][:2])
    return {"headline": headline, "lines": lines[:3], "footnote": project.name or ""}


def _placeholder(project: Project, scene: Scene, duration: float) -> Dict[str, Any]:
    """Last resort: the deterministic mock frame/clip, clearly marked as such."""
    poster = save_frame(
        f"projects/{project.id}/scenes/{scene.id}.svg",
        seed=scene.id,
        title_ar=scene.on_screen_text or scene.purpose,
        subtitle=scene.production_method.replace("_", " "),
        badge=f"SCENE {scene.scene_number}",
        width=720, height=1280,
    )
    clip = save_clip(
        f"projects/{project.id}/scenes/{scene.id}.mp4",
        seed=scene.id, duration_sec=duration,
        label=f"Scene {scene.scene_number}", width=540, height=960,
    )
    return {
        "url": clip or poster,
        "thumbnail_url": poster,
        "renderer": "placeholder",
        "real_media": False,
        "note": "No usable source media — placeholder frame used.",
    }


def render_local_scene(db: Session, project: Project, scene: Scene) -> Dict[str, Any]:
    """Produce a scene without spending anything. Returns a media record."""
    duration = scene_duration(scene)
    method = scene.production_method
    if not render_enabled():
        return _placeholder(project, scene, duration)

    asset = _scene_asset(db, scene)
    source = _asset_local_path(asset)
    look = _look_for(project)
    key = f"projects/{project.id}/scenes/{scene.id}.mp4"

    try:
        if method == ProductionMethod.MOTION_GRAPHICS.value:
            copy = _offer_text(scene, project)
            brand = db.get(BrandKit, project.brand_kit_id) if project.brand_kit_id else None
            record = media_bridge.render_to_storage(
                key,
                lambda target: render_offer_scene(
                    target, duration_sec=duration,
                    primary_color=brand.primary_color if brand else "#0F172A",
                    accent_color=brand.secondary_color if brand else "#2563EB",
                    font_arabic=brand.font_arabic if brand else None,
                    **copy,
                ),
            )
            renderer = "motion_graphics"

        elif method == ProductionMethod.ORIGINAL_VIDEO.value and source:
            info = probe_media(source)
            if info.kind != "video":
                return _placeholder(project, scene, duration)
            ops = dict(scene.remix_ops or {})
            ops.setdefault("op", "trim")
            ops.setdefault("start", 0.0)
            ops.setdefault("end", min(float(ops.get("start", 0.0)) + duration, info.duration_sec or duration))
            ops.setdefault("look", look)
            ops.setdefault("reframe", "crop" if info.orientation != "portrait" else "crop")
            ops.setdefault("mute", True)
            record = media_bridge.render_to_storage(
                key, lambda target: apply_remix(source, target, op_from_dict(ops))
            )
            renderer = "video_remix"

        elif source and probe_media(source).kind == "image":
            info = probe_media(source)
            analysis = (asset.analysis or {}) if asset else {}
            # Every photo scene gets a real move, chosen for where it sits.
            #
            # `ORIGINAL_PHOTO` used to be pinned to `controlled_zoom` — a 6%
            # creep, written as "held, not frozen". With two of four scenes on
            # that method, half the reel barely moved, and every cut between
            # them was hard. That is the difference between an edit and a
            # slideshow, and the user named it before this changed.
            #
            # `recommend_motion` already knows the rules that matter: an offer
            # or price card stays calm, the hook pushes in, a tall frame
            # travels vertically, and everything else walks the rotation by
            # scene number so two neighbours never repeat a move.
            motion = (
                scene.camera_movement
                if scene.camera_movement in MOTION_PRESETS
                else recommend_motion(
                    index=scene.scene_number - 1,
                    orientation=info.orientation,
                    is_hook=scene.is_hook,
                    purpose=scene.purpose or "",
                    motion_potential=float(analysis.get("motion_potential", 0.6) or 0.6),
                )
            )
            record = media_bridge.render_to_storage(
                key,
                lambda target: render_photo_motion(
                    source, target, duration_sec=duration, motion=motion, look=look,
                    fade_in=0.3 if scene.is_hook else 0.0,
                ),
            )
            renderer = f"photo_motion:{motion}"
        else:
            return _placeholder(project, scene, duration)

    except Exception as exc:  # noqa: BLE001 - a render failure must be reported, not hidden
        log.warning("scene %s local render failed (%s): %s", scene.id, method, exc)
        fallback = _placeholder(project, scene, duration)
        fallback["note"] = f"Local render failed: {exc}"
        return fallback

    thumb_key = f"projects/{project.id}/scenes/{scene.id}.png"
    thumbnail_url = None
    try:
        thumb_record = media_bridge.render_to_storage(
            thumb_key,
            lambda target: {"ok": bool(make_thumbnail(record["path"], target, at_sec=min(duration / 2, 1.5)))},
        )
        thumbnail_url = thumb_record["url"]
    except Exception as exc:  # noqa: BLE001
        log.debug("scene thumbnail failed: %s", exc)

    info = probe_media(record["path"])
    return {
        "url": record["url"],
        "thumbnail_url": thumbnail_url,
        "renderer": renderer,
        "real_media": True,
        "duration_sec": info.duration_sec,
        "width": info.width,
        "height": info.height,
        "size_bytes": info.size_bytes,
        "source_asset_id": asset.id if asset else None,
    }


def normalise_provider_output(project: Project, scene: Scene, downloaded_path: str,
                              *, is_image: bool) -> Dict[str, Any]:
    """Bring a provider's output into our storage and our output format.

    Provider URLs expire; provider aspect ratios drift. Neither is allowed into
    the timeline, so generated media is re-encoded to the house format the same
    way local media is.
    """
    duration = scene_duration(scene)
    key = f"projects/{project.id}/scenes/{scene.id}.mp4"
    if is_image:
        record = media_bridge.render_to_storage(
            key,
            lambda target: render_photo_motion(
                downloaded_path, target, duration_sec=duration,
                motion=scene.camera_movement or "push_in", look="neutral",
            ),
        )
        renderer = "ai_image+motion"
    else:
        record = media_bridge.render_to_storage(
            key,
            lambda target: apply_remix(
                downloaded_path, target,
                RemixOp(op="reframe", start=0.0, end=duration, reframe="crop", mute=True),
            ),
        )
        renderer = "ai_video+normalise"
    info = probe_media(record["path"])
    return {"url": record["url"], "renderer": renderer, "real_media": True,
            "duration_sec": info.duration_sec, "width": info.width, "height": info.height}
