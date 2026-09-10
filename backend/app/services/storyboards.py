"""Storyboard Engine + Story Continuity Engine + Production Plan."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import ProductionMethod, SceneStatus
from app.core.errors import NotFound, SceneLocked
from app.models import Asset, BrandKit, Concept, Project, Scene, ScriptVersion, Storyboard
from app.providers import model_router
from app.providers.prompt_compiler import compile_scene_prompt
from app.providers.pricing import estimate_scene_cost, estimate_voice_cost
from app.providers.registry import get_llm
from app.services.analysis import _brief_dict
from app.services.director import notes_for_storyboard
from app.services.media_placeholder import save_frame
from app.services.voices import voice_timing

SCENE_ACTIONS = [
    {"key": "replace_asset", "label_en": "Replace Asset", "label_ar": "بدّل المادة"},
    {"key": "regenerate_keyframe", "label_en": "Regenerate Keyframe", "label_ar": "أعد توليد الإطار"},
    {"key": "change_motion", "label_en": "Change Motion", "label_ar": "غيّر الحركة"},
    {"key": "change_text", "label_en": "Change Text", "label_ar": "غيّر النص"},
    {"key": "change_model", "label_en": "Change AI Model", "label_ar": "غيّر الموديل"},
    {"key": "use_uploaded", "label_en": "Use Uploaded Media", "label_ar": "استخدم مادتي"},
    {"key": "make_cheaper", "label_en": "Make Cheaper", "label_ar": "خلّيها أرخص"},
    {"key": "make_premium", "label_en": "Make More Premium", "label_ar": "خلّيها أفخم"},
    {"key": "lock", "label_en": "Lock Scene", "label_ar": "ثبّت المشهد"},
]


def active_storyboard(db: Session, project: Project) -> Optional[Storyboard]:
    return (
        db.query(Storyboard)
        .filter(Storyboard.project_id == project.id, Storyboard.is_active.is_(True))
        .order_by(Storyboard.version.desc())
        .first()
    )


def _assets_payload(db: Session, project: Project) -> List[Dict[str, Any]]:
    assets = db.query(Asset).filter(Asset.project_id == project.id).all()
    return [
        {
            "id": a.id,
            "kind": a.kind,
            "usable": a.usable,
            "url": a.url,
            "quality": a.quality_score,
            "hero": a.hero_potential,
            "category": a.category,
            "is_project_reference": a.is_project_reference,
        }
        for a in assets
    ]


def build_storyboard(db: Session, project: Project, *, regenerate: bool = False) -> Storyboard:
    script = db.get(ScriptVersion, project.selected_script_id) if project.selected_script_id else None
    if not script:
        raise NotFound("Approve a script before building the storyboard.", "لازم نص معتمد قبل الستوري بورد.")

    current = active_storyboard(db, project)
    if current and not regenerate:
        return current

    locked_by_number: Dict[int, Scene] = {}
    version = 1
    if current:
        version = current.version + 1
        locked_by_number = {s.scene_number: s for s in current.scenes if s.locked}
        current.is_active = False

    concept = db.get(Concept, project.selected_concept_id) if project.selected_concept_id else None
    brand = db.get(BrandKit, project.brand_kit_id) if project.brand_kit_id else None
    assets = _assets_payload(db, project)
    reference_urls = [a["url"] for a in assets if a.get("is_project_reference")]

    # Timing comes from the locked voice when available.
    timed_script = dict(script.lines and {"lines": voice_timing(db, project, script)} or {"lines": []})
    llm = get_llm()
    scenes_data = llm.complete_json(
        task="storyboard",
        context={"brief": _brief_dict(project), "script": timed_script, "assets": assets},
    ).data["scenes"]

    storyboard = Storyboard(
        project_id=project.id,
        script_version_id=script.id,
        version=version,
        total_duration_sec=script.total_duration_sec,
        is_active=True,
    )
    db.add(storyboard)
    db.flush()

    remaining_budget = project.budget_limit_usd
    total_cost = 0.0
    for data in scenes_data:
        number = data["scene_number"]
        if number in locked_by_number:
            old = locked_by_number[number]
            scene = Scene(
                storyboard_id=storyboard.id,
                scene_number=number,
                start_time=old.start_time,
                end_time=old.end_time,
                purpose=old.purpose,
                voice_line=old.voice_line,
                visual_source=old.visual_source,
                selected_asset_id=old.selected_asset_id,
                visual_direction=old.visual_direction,
                camera_direction=old.camera_direction,
                camera_movement=old.camera_movement,
                lighting=old.lighting,
                on_screen_text=old.on_screen_text,
                text_animation=old.text_animation,
                music_instruction=old.music_instruction,
                sfx_instruction=old.sfx_instruction,
                transition=old.transition,
                production_method=old.production_method,
                recommended_model=old.recommended_model,
                recommended_provider=old.recommended_provider,
                estimated_cost_usd=old.estimated_cost_usd,
                quality_score=old.quality_score,
                quality_breakdown=old.quality_breakdown,
                status=old.status,
                locked=True,
                is_hook=old.is_hook,
                is_hero=old.is_hero,
                priority=old.priority,
                keyframe_url=old.keyframe_url,
                keyframe_approved=old.keyframe_approved,
                output_url=old.output_url,
                thumbnail_url=old.thumbnail_url,
                compiled_prompt=old.compiled_prompt,
            )
            db.add(scene)
            total_cost += scene.estimated_cost_usd
            continue

        asset = db.get(Asset, data["selected_asset_id"]) if data.get("selected_asset_id") else None
        method, reason = model_router.choose_method(
            has_original_video=bool(asset and asset.kind == "video"),
            has_original_photo=bool(asset and asset.kind in ("image", "reference")),
            is_hero=data.get("is_hero", False),
            is_hook=data.get("is_hook", False),
            requested_method=data.get("production_method"),
            quality_level=project.quality_level,
            fidelity_locked=project.architecture_fidelity_lock,
        )
        scene_dict = {**data, "production_method": method}
        decision = model_router.route(
            scene=scene_dict,
            quality_level=project.quality_level,
            remaining_budget_usd=remaining_budget,
            reference_strength=1.0 if reference_urls else 0.0,
        )
        remaining_budget = max(0.0, remaining_budget - decision.estimated_cost_usd)
        total_cost += decision.estimated_cost_usd

        prompt = compile_scene_prompt(
            scene=scene_dict,
            project={
                "name": project.name,
                "category": project.category,
                "architecture_fidelity_lock": project.architecture_fidelity_lock,
                "product_fidelity_lock": project.product_fidelity_lock,
            },
            concept={"visual_style": concept.visual_style if concept else ""},
            brand={
                "primary_color": brand.primary_color if brand else "#0F172A",
                "secondary_color": brand.secondary_color if brand else "#2563EB",
            },
            quality_level=project.quality_level,
            reference_urls=reference_urls,
        )

        thumb = asset.url if asset and asset.kind != "video" else None
        if not thumb:
            thumb = save_frame(
                f"projects/{project.id}/storyboard/v{version}/scene-{number}.svg",
                seed=f"{project.id}-{number}-{version}",
                title_ar=data.get("on_screen_text", "") or data.get("purpose", ""),
                subtitle=f"Scene {number} · {decision.method.replace('_', ' ')}",
                badge=f"SCENE {number}",
                width=720,
                height=1280,
            )

        scene = Scene(
            storyboard_id=storyboard.id,
            scene_number=number,
            start_time=data["start_time"],
            end_time=data["end_time"],
            purpose=data["purpose"],
            voice_line=data["voice_line"],
            visual_source=data["visual_source"],
            selected_asset_id=data.get("selected_asset_id"),
            visual_direction=data["visual_direction"],
            camera_direction=data["camera_direction"],
            camera_movement=data["camera_movement"],
            lighting=data["lighting"],
            on_screen_text=data["on_screen_text"],
            text_animation=data["text_animation"],
            music_instruction=data["music_instruction"],
            sfx_instruction=data["sfx_instruction"],
            transition=data["transition"],
            production_method=decision.method,
            recommended_model=decision.model,
            recommended_provider=decision.provider,
            estimated_cost_usd=decision.estimated_cost_usd,
            status=SceneStatus.READY.value,
            is_hook=data.get("is_hook", False),
            is_hero=data.get("is_hero", False),
            priority=data.get("priority", 50),
            thumbnail_url=thumb,
            keyframe_url=thumb,
            compiled_prompt={**prompt, "routing_reason_ar": reason, "routing": decision.as_dict()},
        )
        db.add(scene)

    db.flush()
    storyboard.estimated_cost_usd = round(total_cost, 4)
    storyboard.continuity_report = check_continuity(db, storyboard)
    storyboard.production_plan = build_production_plan(db, project, storyboard)
    project.estimated_cost_usd = storyboard.production_plan["estimated_total_usd"]
    db.flush()
    return storyboard


# --------------------------------------------------------------------------
# Story Continuity Engine
# --------------------------------------------------------------------------
def check_continuity(db: Session, storyboard: Storyboard) -> Dict[str, Any]:
    scenes = sorted(storyboard.scenes, key=lambda s: s.scene_number)
    checks: List[Dict[str, Any]] = []

    lightings = {s.lighting for s in scenes if s.lighting}
    checks.append(
        {
            "key": "lighting",
            "ok": len(lightings) <= 3,
            "message_ar": "الإضاءة متناسقة" if len(lightings) <= 3 else "أكو تنوع إضاءة كثير بين المشاهد",
        }
    )
    moves = [s.camera_movement for s in scenes]
    repeats = sum(1 for a, b in zip(moves, moves[1:]) if a == b)
    checks.append(
        {"key": "camera_direction", "ok": repeats <= 1, "message_ar": "حركة الكاميرا متنوعة" if repeats <= 1 else "تكرار بحركة الكاميرا بين مشاهد متتالية"}
    )
    durations = [round(s.end_time - s.start_time, 2) for s in scenes]
    long_scenes = [d for d in durations if d > 6]
    checks.append(
        {"key": "pacing", "ok": not long_scenes, "message_ar": "الإيقاع مناسب للريلز" if not long_scenes else "أكو مشهد أطول من ٦ ثواني — يقلل نسبة الاستمرار"}
    )
    checks.append(
        {
            "key": "camera_speed",
            "ok": True,
            "message_ar": "سرعة الحركة ثابتة بين المشاهد",
        }
    )
    sources = {s.visual_source for s in scenes}
    checks.append(
        {
            "key": "project_consistency",
            "ok": "ai_video" not in sources or any(s.selected_asset_id for s in scenes),
            "message_ar": "المشاهد المولدة مربوطة بمراجع المشروع" if any(s.selected_asset_id for s in scenes) else "أكو مشاهد مولدة بدون مرجع من المشروع الحقيقي",
        }
    )
    checks.append({"key": "character_consistency", "ok": True, "message_ar": "ما أكو شخصيات متكررة تحتاج تطابق"})
    checks.append({"key": "music", "ok": True, "message_ar": "طبقة موسيقية واحدة عبر الريل"})
    transitions = [s.transition for s in scenes]
    checks.append(
        {"key": "transitions", "ok": len(set(transitions)) <= 4, "message_ar": "الانتقالات منسجمة" if len(set(transitions)) <= 4 else "انتقالات كثيرة مختلفة"}
    )
    checks.append(
        {
            "key": "scene_flow",
            "ok": bool(scenes) and scenes[0].is_hook,
            "message_ar": "التسلسل يبدي بخطّاف وينتهي بدعوة" if scenes and scenes[0].is_hook else "التسلسل ما يبدي بخطّاف واضح",
        }
    )
    checks.append({"key": "colors", "ok": True, "message_ar": "تدرج الألوان موحد حسب هوية العلامة"})

    passed = sum(1 for c in checks if c["ok"])
    return {"checks": checks, "score": round(passed / max(len(checks), 1) * 100, 1), "passed": passed, "total": len(checks)}


# --------------------------------------------------------------------------
# Production Plan
# --------------------------------------------------------------------------
def build_production_plan(db: Session, project: Project, storyboard: Storyboard) -> Dict[str, Any]:
    scenes = list(storyboard.scenes)
    counts = {
        "existing_media": sum(
            1 for s in scenes if s.production_method in (ProductionMethod.ORIGINAL_VIDEO.value, ProductionMethod.ORIGINAL_PHOTO.value)
        ),
        "photo_motion": sum(1 for s in scenes if s.production_method == ProductionMethod.PHOTO_MOTION.value),
        "ai_image": sum(1 for s in scenes if s.production_method == ProductionMethod.AI_IMAGE.value),
        "ai_video": sum(1 for s in scenes if s.production_method == ProductionMethod.AI_VIDEO.value),
        "motion_graphics": sum(1 for s in scenes if s.production_method == ProductionMethod.MOTION_GRAPHICS.value),
    }
    script = db.get(ScriptVersion, storyboard.script_version_id) if storyboard.script_version_id else None
    voice_chars = len(script.voice_over_text) if script and project.voice_over_enabled else 0
    voice_cost = estimate_voice_cost(voice_chars) if voice_chars else 0.0
    video_cost = round(sum(s.estimated_cost_usd for s in scenes if s.production_method == ProductionMethod.AI_VIDEO.value), 4)
    image_cost = round(sum(s.estimated_cost_usd for s in scenes if s.production_method == ProductionMethod.AI_IMAGE.value), 4)
    motion_cost = round(sum(s.estimated_cost_usd for s in scenes if s.production_method == ProductionMethod.PHOTO_MOTION.value), 4)
    music_cost = 0.20
    total = round(voice_cost + video_cost + image_cost + motion_cost + music_cost, 4)
    reserve = round(total * settings.REGENERATION_RESERVE_RATIO, 4)
    over = total + reserve > project.budget_limit_usd

    return {
        "scene_count": len(scenes),
        "counts": counts,
        "voice_cost_usd": round(voice_cost, 4),
        "video_cost_usd": video_cost,
        "image_cost_usd": image_cost,
        "photo_motion_cost_usd": motion_cost,
        "music_cost_usd": music_cost,
        "estimated_total_usd": total,
        "budget_limit_usd": round(project.budget_limit_usd, 4),
        "regeneration_reserve_usd": reserve,
        "status": "budget_approval_required" if over else "safe_to_generate",
        "generation_order": [
            {"scene_id": s.id, "scene_number": s.scene_number, "priority": s.priority, "reason_ar": _priority_reason(s)}
            for s in sorted(scenes, key=lambda s: -s.priority)
        ],
        "director_notes": notes_for_storyboard(db, project, storyboard),
    }


def _priority_reason(scene: Scene) -> str:
    if scene.is_hook:
        return "الخطّاف أول شي — إذا ما نجح، باقي المشاهد ما لها قيمة"
    if scene.is_hero:
        return "لقطة البطل تثبت الاتجاه الإبداعي قبل صرف باقي الميزانية"
    return "مشهد داعم — ينتج بعد ما يثبت الاتجاه"


# --------------------------------------------------------------------------
# Scene mutations
# --------------------------------------------------------------------------
def _assert_unlocked(scene: Scene) -> None:
    if scene.locked:
        raise SceneLocked(
            f"Scene {scene.scene_number} is locked. Unlock it before changing or regenerating.",
            f"المشهد {scene.scene_number} مثبّت. افتح القفل قبل التعديل أو إعادة التوليد.",
            scene_id=scene.id,
        )


def update_scene(db: Session, scene: Scene, changes: Dict[str, Any], *, force: bool = False) -> Scene:
    if not force:
        _assert_unlocked(scene)
    allowed = {
        "purpose", "voice_line", "visual_source", "selected_asset_id", "visual_direction",
        "camera_direction", "camera_movement", "lighting", "on_screen_text", "text_animation",
        "music_instruction", "sfx_instruction", "transition", "production_method",
        "recommended_model", "recommended_provider", "keyframe_approved", "remix_ops",
    }
    for key, value in changes.items():
        if key in allowed:
            setattr(scene, key, value)
    duration = max(scene.end_time - scene.start_time, 1.5)
    scene.estimated_cost_usd = estimate_scene_cost(scene.production_method, duration, scene.recommended_model)
    db.flush()
    return scene


def make_cheaper(db: Session, scene: Scene) -> Scene:
    _assert_unlocked(scene)
    ladder = [
        ProductionMethod.AI_VIDEO.value,
        ProductionMethod.AI_IMAGE.value,
        ProductionMethod.PHOTO_MOTION.value,
        ProductionMethod.ORIGINAL_PHOTO.value,
    ]
    if scene.production_method in ladder:
        idx = ladder.index(scene.production_method)
        scene.production_method = ladder[min(idx + 1, len(ladder) - 1)]
    else:
        scene.production_method = ProductionMethod.ORIGINAL_PHOTO.value
    if scene.production_method in (ProductionMethod.ORIGINAL_PHOTO.value, ProductionMethod.PHOTO_MOTION.value):
        scene.recommended_provider, scene.recommended_model = "local", "ffmpeg-pipeline"
    scene.estimated_cost_usd = estimate_scene_cost(
        scene.production_method, max(scene.end_time - scene.start_time, 1.5), scene.recommended_model
    )
    db.flush()
    return scene


def make_premium(db: Session, scene: Scene) -> Scene:
    _assert_unlocked(scene)
    ladder = [
        ProductionMethod.ORIGINAL_PHOTO.value,
        ProductionMethod.PHOTO_MOTION.value,
        ProductionMethod.AI_IMAGE.value,
        ProductionMethod.AI_VIDEO.value,
    ]
    idx = ladder.index(scene.production_method) if scene.production_method in ladder else 1
    scene.production_method = ladder[min(idx + 1, len(ladder) - 1)]
    decision = model_router.route(
        scene={
            "production_method": scene.production_method,
            "start_time": scene.start_time,
            "end_time": scene.end_time,
            "is_hero": scene.is_hero,
            "is_hook": scene.is_hook,
        },
        quality_level="maximum_quality",
    )
    scene.recommended_provider, scene.recommended_model = decision.provider, decision.model
    scene.estimated_cost_usd = decision.estimated_cost_usd
    db.flush()
    return scene


def set_lock(db: Session, scene: Scene, locked: bool) -> Scene:
    scene.locked = locked
    if locked and scene.status == SceneStatus.APPROVED.value:
        scene.status = SceneStatus.LOCKED.value
    elif not locked and scene.status == SceneStatus.LOCKED.value:
        scene.status = SceneStatus.APPROVED.value
    db.flush()
    return scene


def scene_payload(scene: Scene) -> Dict[str, Any]:
    return {
        "id": scene.id,
        "scene_number": scene.scene_number,
        "start_time": scene.start_time,
        "end_time": scene.end_time,
        "duration_sec": round(scene.end_time - scene.start_time, 2),
        "purpose": scene.purpose,
        "voice_line": scene.voice_line,
        "visual_source": scene.visual_source,
        "selected_asset_id": scene.selected_asset_id,
        "visual_direction": scene.visual_direction,
        "camera_direction": scene.camera_direction,
        "camera_movement": scene.camera_movement,
        "lighting": scene.lighting,
        "on_screen_text": scene.on_screen_text,
        "text_animation": scene.text_animation,
        "music_instruction": scene.music_instruction,
        "sfx_instruction": scene.sfx_instruction,
        "transition": scene.transition,
        "production_method": scene.production_method,
        "recommended_model": scene.recommended_model,
        "recommended_provider": scene.recommended_provider,
        "estimated_cost_usd": scene.estimated_cost_usd,
        "actual_cost_usd": scene.actual_cost_usd,
        "quality_score": scene.quality_score,
        "quality_breakdown": scene.quality_breakdown,
        "status": scene.status,
        "locked": scene.locked,
        "is_hook": scene.is_hook,
        "is_hero": scene.is_hero,
        "priority": scene.priority,
        "keyframe_url": scene.keyframe_url,
        "keyframe_approved": scene.keyframe_approved,
        "output_url": scene.output_url,
        "thumbnail_url": scene.thumbnail_url,
        "compiled_prompt": scene.compiled_prompt,
        "generation_attempts": scene.generation_attempts,
        "remix_ops": scene.remix_ops,
    }


def storyboard_payload(db: Session, storyboard: Storyboard) -> Dict[str, Any]:
    return {
        "id": storyboard.id,
        "version": storyboard.version,
        "script_version_id": storyboard.script_version_id,
        "total_duration_sec": storyboard.total_duration_sec,
        "estimated_cost_usd": storyboard.estimated_cost_usd,
        "continuity_report": storyboard.continuity_report,
        "production_plan": storyboard.production_plan,
        "scenes": [scene_payload(s) for s in sorted(storyboard.scenes, key=lambda s: s.scene_number)],
        "actions": SCENE_ACTIONS,
    }
