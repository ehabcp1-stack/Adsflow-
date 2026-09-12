"""Seed the demo organisation, brand kit, voices and the «مدينة الورد» project.

Runs the entire workflow with Mock Providers so the whole product is testable
in the browser immediately — no paid API keys required.

    python -m app.seed          # create if missing
    python -m app.seed --reset  # drop and rebuild
"""
from __future__ import annotations

import sys
from typing import List

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import Base, SessionLocal, engine, init_db
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
from app.services.jobs import execute_job
from app.seed_media import DEMO_PHOTOS, build_demo_media
from app.services.media_placeholder import save_clip, save_frame

DEMO_IMAGES = [
    ("exterior", "واجهة المشروع", "Exterior — golden hour"),
    ("exterior", "مدخل رئيسي", "Main entrance"),
    ("interior", "صالة معيشة", "Living area"),
    ("interior", "مطبخ مفتوح", "Open kitchen"),
    ("amenity", "حدائق ومسارات", "Green walkways"),
    ("amenity", "نادي ومسبح", "Club & pool"),
    ("location", "قريب من كل شي", "Location map"),
    ("detail", "تفاصيل التشطيب", "Finishing detail"),
]


def _create_demo_assets(db: Session, org: Organization, project: Project) -> List[Asset]:
    """Give the demo project REAL media so the real pipeline has real work.

    Vector placeholders would make photo motion, remixing and QC meaningless —
    there would be nothing to pan across, cut or measure. These are synthesised
    files, but they are genuine JPEG/H.264/AAC with real pixels and real shot
    changes.
    """
    media = build_demo_media(project.id)
    assets: List[Asset] = []

    for record in media["photos"]:
        photo = record["meta"]
        asset = Asset(
            organization_id=org.id,
            project_id=project.id,
            kind="image",
            filename=f"{photo.key}.jpg",
            storage_key=record["key"],
            url=record["url"],
            thumbnail_url=record["url"],
            mime_type="image/jpeg",
            size_bytes=record["size_bytes"],
            width=record["width"],
            height=record["height"],
            orientation="portrait" if record["height"] > record["width"] else "landscape",
            category=photo.category,
            is_project_reference=photo.is_reference,
            suggested_use=photo.subtitle,
            tags=["مدينة الورد", photo.category],
        )
        db.add(asset)
        assets.append(asset)

    video_record = media.get("video")
    if video_record:
        video = Asset(
            organization_id=org.id,
            project_id=project.id,
            kind="video",
            filename="site-tour.mp4",
            storage_key=video_record["key"],
            url=video_record["url"],
            thumbnail_url=assets[0].url if assets else None,
            mime_type="video/mp4",
            size_bytes=video_record["size_bytes"],
            width=video_record["width"],
            height=video_record["height"],
            duration_sec=video_record["duration_sec"],
            orientation="landscape",
            category="tour",
            tags=["مدينة الورد", "tour"],
        )
        db.add(video)
        assets.append(video)

    logo_record = media.get("logo")
    if logo_record:
        db.add(
            Asset(
                organization_id=org.id, project_id=project.id, kind="logo",
                filename="logo.png", storage_key=logo_record["key"],
                url=logo_record["url"], thumbnail_url=logo_record["url"],
                mime_type="image/png", size_bytes=logo_record["size_bytes"],
                width=logo_record["width"], height=logo_record["height"],
                orientation="square", tags=["brand"],
            )
        )
    db.flush()

    # Measure what was just written, exactly as a customer upload would be.
    from app.services.assets import analyze_asset

    for asset in assets:
        try:
            analyze_asset(db, asset)
        except Exception as exc:  # noqa: BLE001 - seeding must never hard-fail
            print(f"  ! analysis skipped for {asset.filename}: {exc}")
    db.flush()
    project.thumbnail_url = project.thumbnail_url or (assets[0].url if assets else None)
    return assets


def _run_jobs_sync(db: Session, project: Project) -> None:
    """Finish every job before the seeder moves on.

    Jobs were already dispatched to the background pool, so this claims what is
    still queued and then waits for the rest. It must never execute a job the
    pool is already running — two writers on one output file corrupt it.
    """
    # One at a time, and never while another is running. Two things depend on
    # that: a job the pool is already running must not get a second executor
    # (two FFmpeg processes on one output file produce a corrupt clip that
    # still looks plausible), and the voice job retimes the storyboard before
    # releasing the scene jobs — a scene cut while the voice is still being
    # synthesised is cut to the estimate and overruns its slot.
    import time as _time

    deadline = _time.time() + 900
    while _time.time() < deadline:
        db.expire_all()
        jobs = (
            db.query(GenerationJob)
            .filter(GenerationJob.project_id == project.id)
            .order_by(GenerationJob.created_at)
            .all()
        )
        if any(job.status == JobStatus.RUNNING.value for job in jobs):
            _time.sleep(0.5)
            continue
        queued = [j for j in jobs if j.status in (JobStatus.QUEUED.value, JobStatus.RETRYING.value)]
        if not queued:
            break
        execute_job(db, queued[0].id)
    production_service.wait_for_jobs(db, project, timeout_sec=600.0)


def _clear_local_storage() -> None:
    """Remove media from a previous seed. Local backend only — never S3."""
    import shutil
    from pathlib import Path

    if settings.STORAGE_BACKEND != "local":
        return
    root = Path(settings.STORAGE_LOCAL_DIR)
    if not root.exists():
        return
    for child in root.iterdir():
        shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink(missing_ok=True)


def _approve_pending_keyframes(db: Session, project: Project) -> None:
    """Approve every still waiting at the hero-frame gate, then finish the work."""
    storyboard = production_service.active_storyboard(db, project)
    if not storyboard:
        return
    pending = [s for s in storyboard.scenes if s.keyframe_url and not s.keyframe_approved]
    if not pending:
        return
    for scene in pending:
        production_service.approve_keyframe(db, scene, True)
    db.commit()
    _run_jobs_sync(db, project)


def seed(reset: bool = False) -> str:
    if reset:
        Base.metadata.drop_all(bind=engine)
        # Dropping the database orphans every file the old run produced. Left
        # behind they are invisible bytes that the demo snapshot still copies
        # — the export went from 4MB to 10MB of media nobody references.
        _clear_local_storage()
    init_db()
    db = SessionLocal()
    try:
        existing = db.query(Project).filter(Project.name == "مدينة الورد").first()
        if existing and not reset:
            print(f"Demo project already seeded: {existing.id}")
            return existing.id

        org = db.query(Organization).first()
        if not org:
            org = Organization(
                name="TADAFQ", name_ar="تدفق", parent_brand="TADAFQ",
                monthly_budget_usd=settings.MONTHLY_BUDGET_TARGET_USD,
            )
            db.add(org)
            db.flush()

        user = db.query(User).filter(User.email == settings.DEV_USER_EMAIL).first()
        if not user:
            user = User(
                email=settings.DEV_USER_EMAIL,
                full_name="TADAFQ Demo",
                hashed_password=hash_password(settings.DEV_USER_PASSWORD),
                role="owner",
                locale="ar",
                organization_id=org.id,
            )
            db.add(user)
            db.flush()

        voice_service.ensure_demo_voices(db, org.id)

        brand = db.query(BrandKit).filter(BrandKit.organization_id == org.id).first()
        if not brand:
            brand = BrandKit(
                organization_id=org.id,
                name="Madinat Al-Ward",
                name_ar="مدينة الورد",
                primary_color="#0F172A",
                secondary_color="#2563EB",
                accent_color="#C9A227",
                font_arabic="Cairo",
                font_latin="Inter",
                caption_style={"template": "bold_bar", "size": "lg", "position": "lower_third"},
                editing_style="emotional_cinematic",
                music_profile={"mood": "warm cinematic", "energy": 0.5},
                cta_template={"text": "احجز موعد زيارة اليوم", "style": "pill"},
                end_screen_template={"style": "logo_center", "duration_sec": 2.5,
                                     "tagline": "سكن ذكي بقلب بغداد"},
                phone="07701234567",
                website="tadafq.com",
                social_handles={"instagram": "@tadafq", "facebook": "tadafq"},
                preferred_phrases=["أقساط مريحة", "تسليم بالوقت", "موقع مدروس"],
                forbidden_phrases=["الأفضل على الإطلاق", "أرباح مضمونة"],
                pronunciation_rules={"TADAFQ": "تَدَفُّق"},
                is_default=True,
            )
            db.add(brand)
            db.flush()

        project = Project(
            organization_id=org.id,
            created_by_id=user.id,
            brand_kit_id=brand.id,
            name="مدينة الورد",
            category="real_estate",
            goal="leads",
            platform="instagram_reels",
            duration_sec=30,
            language="iraqi_arabic",
            dialect="iraqi_emotional",
            tone="emotional",
            target_audience="عوائل عراقية ٢٨–٤٥ سنة، دخل متوسط وفوق، يدورون على سكن مناسب ببغداد",
            key_information=(
                "وحدات سكنية بمساحات ١٥٠ و٢٠٠ متر\n"
                "دفعة أولى ٢٥٪ وأقساط لحد ٤ سنوات\n"
                "المشروع على الشارع العام وقريب من المدارس والأسواق\n"
                "تسليم أول مرحلة خلال ٦ أشهر"
            ),
            cta="احجز موعد زيارة اليوم",
            production_mode="auto_smart",
            quality_level="smart_premium",
            voice_over_enabled=True,
            budget_limit_usd=12.0,
            editing_style="emotional_cinematic",
        )
        db.add(project)
        db.flush()

        demo_assets = _create_demo_assets(db, org, project)
        if not brand.logo_url:
            logo_asset = (
                db.query(Asset)
                .filter(Asset.project_id == project.id, Asset.kind == "logo")
                .first()
            )
            if logo_asset:
                brand.logo_url = logo_asset.url
                db.flush()
        db.commit()

        # --- Analysis ----------------------------------------------------
        approval_service.set_state(db, project, ProjectState.ANALYZING, note="seed")
        analysis = run_analysis(db, project)
        approval_service.set_state(db, project, ProjectState.ANALYSIS_READY, note="seed")
        approval_service.approve(
            db, project=project, entity=ApprovalEntity.ANALYSIS, entity_id=analysis.id,
            version=analysis.version, user_id=user.id, notes="seeded",
        )
        approval_service.set_state(db, project, ProjectState.CONCEPT_REVIEW, note="seed")
        db.commit()

        # --- Concepts ----------------------------------------------------
        created = concept_service.generate_concepts(db, project)
        chosen = next((c for c in created if c.is_recommended), created[0])
        concept_service.select_concept(db, project, chosen.id)
        approval_service.approve(
            db, project=project, entity=ApprovalEntity.CONCEPT, entity_id=chosen.id,
            version=chosen.version, user_id=user.id, notes="seeded",
        )
        approval_service.set_state(db, project, ProjectState.CONCEPT_APPROVED, note="seed")
        db.commit()

        # --- Script ------------------------------------------------------
        scripts = script_service.generate_scripts(db, project)
        primary = next(s for s in scripts if s.variant == "primary")
        approval_service.set_state(db, project, ProjectState.SCRIPT_REVIEW, note="seed")
        approval_service.approve(
            db, project=project, entity=ApprovalEntity.SCRIPT, entity_id=primary.id,
            version=primary.version, user_id=user.id, notes="seeded",
        )
        approval_service.set_state(db, project, ProjectState.SCRIPT_APPROVED, note="seed")
        db.commit()

        # --- Voice -------------------------------------------------------
        profiles = voice_service.ensure_demo_voices(db, org.id)
        emotional = next((p for p in profiles if p.dialect == "iraqi_emotional"), profiles[0])
        voice_service.select_voice(db, project, emotional.id, lock=True)
        approval_service.approve(
            db, project=project, entity=ApprovalEntity.VOICE, entity_id=emotional.id, user_id=user.id, notes="seeded"
        )
        brand.voice_profile_id = emotional.id
        db.commit()

        # --- Storyboard --------------------------------------------------
        storyboard = storyboard_service.build_storyboard(db, project)
        approval_service.set_state(db, project, ProjectState.STORYBOARD_REVIEW, note="seed")
        approval_service.approve(
            db, project=project, entity=ApprovalEntity.STORYBOARD, entity_id=storyboard.id,
            version=storyboard.version, user_id=user.id, notes="seeded",
        )
        approval_service.set_state(db, project, ProjectState.STORYBOARD_APPROVED, note="seed")
        approval_service.approve(
            db, project=project, entity=ApprovalEntity.PRODUCTION_PLAN, entity_id=storyboard.id,
            version=storyboard.version, user_id=user.id, notes="seeded",
        )
        approval_service.set_state(db, project, ProjectState.PRODUCTION_READY, note="seed")
        db.commit()

        # --- Production (synchronous for a deterministic seed) ------------
        production_service.start_production(db, project, user_id=user.id)
        _run_jobs_sync(db, project)
        # Hero-frame-first parks AI-video scenes on an approved-keyframe gate.
        # The seeder plays the human who looks at each still and says yes —
        # that is a real step in the product, not a bypass, so it runs through
        # the same approval path the UI calls.
        _approve_pending_keyframes(db, project)
        production_service.finish_production(db, project)
        db.commit()

        # --- Editing → QC → Export ---------------------------------------
        editing_service.render_project(db, project)
        db.commit()
        report = qc_service.run_qc(db, project)
        db.commit()
        approval_service.approve(
            db, project=project, entity=ApprovalEntity.FINAL, entity_id=report.id,
            version=report.version, user_id=user.id, notes="seeded",
        )
        approval_service.set_state(db, project, ProjectState.FINAL_APPROVAL, note="seed")
        export_service.create_export(db, project, variant="master", force=True)
        export_service.create_export(db, project, variant="with_captions", force=True)
        export_service.create_export(db, project, variant="thumbnail", force=True)
        db.commit()

        print(
            f"Seeded demo project «{project.name}» ({project.id})\n"
            f"  state       : {project.state}\n"
            f"  qc score    : {report.total_score}\n"
            f"  est. cost   : ${project.estimated_cost_usd:.2f}\n"
            f"  actual cost : ${project.actual_cost_usd:.2f} (mock providers)\n"
            f"  login       : {settings.DEV_USER_EMAIL} / {settings.DEV_USER_PASSWORD}"
        )
        return project.id
    finally:
        db.close()


if __name__ == "__main__":
    seed(reset="--reset" in sys.argv)
