"""Build a complete reel from real customer photos, on local render only.

This is the honest preview: it runs the same services the product runs, with
every AI provider mocked, so what comes out shows exactly what the editing,
captions, timing, branding and mix will look like on the customer's own
material — at zero cost and with nothing invented about the property.

    python -m scripts.preview_from_photos <photo-dir> --name "اسم المشروع"
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path
from typing import List

from app.core.config import settings
from app.core.db import SessionLocal, init_db
from app.core.enums import ApprovalEntity, JobStatus, ProjectState
from app.core.security import hash_password
from app.models import Asset, BrandKit, GenerationJob, Organization, Project, User
from app.services import approvals as approval_service
from app.services import concepts as concept_service
from app.services import editing as editing_service
from app.services import exports as export_service
from app.services import production as production_service
from app.services import qc as qc_service
from app.services import scripts as script_service
from app.services import storyboards as storyboard_service
from app.services import voices as voice_service
from app.services.analysis import run_analysis
from app.services.assets import analyze_asset
from app.services.jobs import execute_job
from app.services.storage import get_storage

#: What each photo is, in the order they were supplied. Captions describe only
#: what is visible — nothing about price, area or delivery is invented here.
PHOTO_ROLES = [
    ("exterior", "فلل بإضاءة الغروب", True),
    ("amenity", "شارع تجاري ومحلات", False),
    ("location", "ترام ومسارات دراجات", False),
    ("amenity", "مقاهي وواجهات الشارع", False),
    ("location", "المخطط العام للمدينة", False),
    ("exterior", "مدخل الفلل والنخيل", True),
    ("exterior", "شارع سكني وقت الغروب", True),
    ("exterior", "منطقة الأعمال من الجو", False),
]


def _run_jobs(db, project: Project) -> None:
    deadline = time.time() + 900
    while time.time() < deadline:
        db.expire_all()
        jobs = (
            db.query(GenerationJob)
            .filter(GenerationJob.project_id == project.id)
            .order_by(GenerationJob.created_at)
            .all()
        )
        if any(j.status == JobStatus.RUNNING.value for j in jobs):
            time.sleep(0.5)
            continue
        queued = [j for j in jobs if j.status in (JobStatus.QUEUED.value, JobStatus.RETRYING.value)]
        if not queued:
            break
        execute_job(db, queued[0].id)
    production_service.wait_for_jobs(db, project, timeout_sec=600.0)


def build(photo_dir: str, name: str, key_info: str, cta: str, phone: str) -> str:
    init_db()
    db = SessionLocal()
    try:
        org = db.query(Organization).first()
        if not org:
            org = Organization(name="TADAFQ", name_ar="تدفق", parent_brand="TADAFQ",
                               monthly_budget_usd=settings.MONTHLY_BUDGET_TARGET_USD)
            db.add(org)
            db.flush()
        user = db.query(User).filter(User.email == settings.DEV_USER_EMAIL).first()
        if not user:
            user = User(email=settings.DEV_USER_EMAIL, full_name="TADAFQ",
                        hashed_password=hash_password(settings.DEV_USER_PASSWORD),
                        role="owner", locale="ar", organization_id=org.id)
            db.add(user)
            db.flush()
        voice_service.ensure_demo_voices(db, org.id)

        brand = BrandKit(
            organization_id=org.id, name=name, name_ar=name,
            primary_color="#0F172A", secondary_color="#2563EB", accent_color="#C9A227",
            font_arabic="Cairo", font_latin="Inter",
            caption_style={"template": "bold_bar", "size": "lg", "position": "lower_third"},
            editing_style="emotional_cinematic",
            music_profile={"mood": "warm cinematic", "energy": 0.5},
            cta_template={"text": cta, "style": "pill"},
            end_screen_template={"style": "logo_center", "duration_sec": 2.5, "tagline": name},
            phone=phone, website="tadafq.com", is_default=False,
        )
        db.add(brand)
        db.flush()

        project = Project(
            organization_id=org.id, created_by_id=user.id, brand_kit_id=brand.id,
            name=name, category="real_estate", goal="leads", platform="instagram_reels",
            duration_sec=30, language="iraqi_arabic", dialect="iraqi_emotional",
            tone="emotional",
            target_audience="عوائل عراقية ٢٨–٤٥ سنة يدورون على سكن بمجمع متكامل",
            key_information=key_info, cta=cta,
            production_mode="auto_smart", quality_level="smart_premium",
            voice_over_enabled=True, budget_limit_usd=12.0,
            editing_style="emotional_cinematic",
        )
        db.add(project)
        db.flush()

        storage = get_storage()
        files = sorted(Path(photo_dir).glob("*.jpg")) + sorted(Path(photo_dir).glob("*.png"))
        if not files:
            raise SystemExit(f"no photos found in {photo_dir}")
        assets: List[Asset] = []
        for index, path in enumerate(files):
            category, caption, is_ref = (
                PHOTO_ROLES[index] if index < len(PHOTO_ROLES) else ("exterior", "لقطة", False)
            )
            key = f"projects/{project.id}/uploads/{index:02d}-{path.name}"
            target = storage.local_path(key)
            if target:
                Path(target).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                url = storage.url_for(key)
                size = Path(target).stat().st_size
            else:
                url = storage.put_file(key, str(path), "image/jpeg")
                size = path.stat().st_size
            asset = Asset(
                organization_id=org.id, project_id=project.id, kind="image",
                filename=path.name, storage_key=key, url=url, thumbnail_url=url,
                mime_type="image/jpeg", size_bytes=size, category=category,
                is_project_reference=is_ref, suggested_use=caption,
                tags=[name, category],
            )
            db.add(asset)
            assets.append(asset)
        db.flush()
        for asset in assets:
            try:
                analyze_asset(db, asset)
            except Exception as exc:  # noqa: BLE001
                print(f"  ! analysis skipped for {asset.filename}: {exc}")
        project.thumbnail_url = assets[0].url
        db.commit()
        print(f"registered {len(assets)} real photos")

        approval_service.set_state(db, project, ProjectState.ANALYZING, note="preview")
        analysis = run_analysis(db, project)
        approval_service.set_state(db, project, ProjectState.ANALYSIS_READY, note="preview")
        approval_service.approve(db, project=project, entity=ApprovalEntity.ANALYSIS,
                                 entity_id=analysis.id, version=analysis.version, user_id=user.id)
        approval_service.set_state(db, project, ProjectState.CONCEPT_REVIEW, note="preview")
        db.commit()

        created = concept_service.generate_concepts(db, project)
        chosen = next((c for c in created if c.is_recommended), created[0])
        concept_service.select_concept(db, project, chosen.id)
        approval_service.approve(db, project=project, entity=ApprovalEntity.CONCEPT,
                                 entity_id=chosen.id, version=chosen.version, user_id=user.id)
        approval_service.set_state(db, project, ProjectState.CONCEPT_APPROVED, note="preview")
        db.commit()

        scripts = script_service.generate_scripts(db, project)
        primary = next(s for s in scripts if s.variant == "primary")
        approval_service.set_state(db, project, ProjectState.SCRIPT_REVIEW, note="preview")
        approval_service.approve(db, project=project, entity=ApprovalEntity.SCRIPT,
                                 entity_id=primary.id, version=primary.version, user_id=user.id)
        approval_service.set_state(db, project, ProjectState.SCRIPT_APPROVED, note="preview")
        db.commit()

        profiles = voice_service.ensure_demo_voices(db, org.id)
        voice = next((p for p in profiles if p.dialect == "iraqi_emotional"), profiles[0])
        voice_service.select_voice(db, project, voice.id, lock=True)
        approval_service.approve(db, project=project, entity=ApprovalEntity.VOICE,
                                 entity_id=voice.id, user_id=user.id)
        db.commit()

        storyboard = storyboard_service.build_storyboard(db, project)
        approval_service.set_state(db, project, ProjectState.STORYBOARD_REVIEW, note="preview")
        approval_service.approve(db, project=project, entity=ApprovalEntity.STORYBOARD,
                                 entity_id=storyboard.id, version=storyboard.version, user_id=user.id)
        approval_service.set_state(db, project, ProjectState.STORYBOARD_APPROVED, note="preview")
        approval_service.approve(db, project=project, entity=ApprovalEntity.PRODUCTION_PLAN,
                                 entity_id=storyboard.id, version=storyboard.version, user_id=user.id)
        approval_service.set_state(db, project, ProjectState.PRODUCTION_READY, note="preview")
        db.commit()

        production_service.start_production(db, project, user_id=user.id)
        _run_jobs(db, project)
        storyboard = storyboard_service.active_storyboard(db, project)
        pending = [s for s in storyboard.scenes if s.keyframe_url and not s.keyframe_approved]
        for scene in pending:
            production_service.approve_keyframe(db, scene, True)
        if pending:
            db.commit()
            _run_jobs(db, project)
        production_service.finish_production(db, project)
        db.commit()

        editing_service.render_project(db, project)
        db.commit()
        report = qc_service.run_qc(db, project)
        db.commit()
        approval_service.approve(db, project=project, entity=ApprovalEntity.FINAL,
                                 entity_id=report.id, version=report.version, user_id=user.id)
        approval_service.set_state(db, project, ProjectState.FINAL_APPROVAL, note="preview")
        export_service.create_export(db, project, variant="master", force=True)
        db.commit()

        counts: dict = {}
        for scene in storyboard_service.active_storyboard(db, project).scenes:
            counts[scene.production_method] = counts.get(scene.production_method, 0) + 1
        print(
            f"\nproject : {project.name} ({project.id})\n"
            f"state   : {project.state}\n"
            f"qc      : {report.total_score} — {report.verdict}\n"
            f"methods : {counts}\n"
            f"est     : ${project.estimated_cost_usd:.2f}   actual: ${project.actual_cost_usd:.2f}"
        )
        return project.id
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("photo_dir")
    parser.add_argument("--name", required=True)
    parser.add_argument("--key-info", default="")
    parser.add_argument("--cta", default="احجز موعد زيارة اليوم")
    parser.add_argument("--phone", default="07700000000")
    args = parser.parse_args()
    sys.exit(0 if build(args.photo_dir, args.name, args.key_info, args.cta, args.phone) else 1)
