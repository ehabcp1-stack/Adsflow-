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
    assets: List[Asset] = []
    for index, (category, title_ar, subtitle) in enumerate(DEMO_IMAGES):
        key = f"demo/{project.id}/image-{index + 1}.svg"
        url = save_frame(
            key,
            seed=f"warda-{index}",
            title_ar=title_ar,
            subtitle=subtitle,
            badge=f"SOURCE {index + 1}",
            width=1080,
            height=1350,
        )
        asset = Asset(
            organization_id=org.id,
            project_id=project.id,
            kind="image",
            filename=f"madinat-alward-{index + 1}.jpg",
            storage_key=key,
            url=url,
            thumbnail_url=url,
            mime_type="image/svg+xml",
            size_bytes=48_000,
            width=1080,
            height=1350,
            orientation="portrait",
            category=category,
            is_project_reference=index < 3,
            tags=["مدينة الورد", category],
        )
        db.add(asset)
        assets.append(asset)

    clip_key = f"demo/{project.id}/site-tour.mp4"
    clip_url = save_clip(clip_key, seed="warda-tour", duration_sec=12.0, label="Site Tour", width=540, height=960)
    poster = save_frame(
        f"demo/{project.id}/site-tour.svg", seed="warda-tour", title_ar="جولة بالموقع",
        subtitle="Site tour — 12s", badge="SOURCE VIDEO", width=1080, height=1350,
    )
    video = Asset(
        organization_id=org.id,
        project_id=project.id,
        kind="video",
        filename="site-tour.mp4",
        storage_key=clip_key,
        url=clip_url or poster,
        thumbnail_url=poster,
        mime_type="video/mp4",
        size_bytes=1_200_000,
        width=1080,
        height=1920,
        duration_sec=12.0,
        orientation="portrait",
        tags=["مدينة الورد", "tour"],
    )
    db.add(video)
    assets.append(video)

    logo = save_frame(
        f"demo/{project.id}/logo.svg", seed="tadafq-logo", title_ar="مدينة الورد",
        subtitle="TADAFQ", badge="LOGO", width=600, height=600,
    )
    db.add(
        Asset(
            organization_id=org.id, project_id=project.id, kind="logo", filename="logo.svg",
            url=logo, thumbnail_url=logo, mime_type="image/svg+xml", width=600, height=600,
            orientation="square", tags=["brand"],
        )
    )
    db.flush()
    return assets


def _run_jobs_sync(db: Session, project: Project) -> None:
    jobs = db.query(GenerationJob).filter(GenerationJob.project_id == project.id).all()
    for job in jobs:
        if job.status in (JobStatus.QUEUED.value, JobStatus.RETRYING.value):
            execute_job(db, job.id)


def seed(reset: bool = False) -> str:
    if reset:
        Base.metadata.drop_all(bind=engine)
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
                end_screen_template={"style": "logo_center", "duration_sec": 2.5},
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

        _create_demo_assets(db, org, project)
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
