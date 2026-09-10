"""Project workflow models: brief → analysis → concepts → script → storyboard
→ production → editing → QC → export, plus approvals, costs and jobs."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import GUID, Base, TimestampMixin, new_uuid
from app.core.enums import (
    ApprovalStatus,
    CostStatus,
    EditingStyle,
    JobStatus,
    ProjectState,
    QualityLevel,
)


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(GUID, ForeignKey("organizations.id"))
    organization: Mapped["Organization"] = relationship(back_populates="projects")  # noqa: F821
    created_by_id: Mapped[Optional[str]] = mapped_column(GUID, ForeignKey("users.id"), nullable=True)
    brand_kit_id: Mapped[Optional[str]] = mapped_column(GUID, ForeignKey("brand_kits.id"), nullable=True)

    # --- Brief -----------------------------------------------------------
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(80), default="real_estate")
    goal: Mapped[str] = mapped_column(String(40), default="leads")
    platform: Mapped[str] = mapped_column(String(40), default="instagram_reels")
    duration_sec: Mapped[int] = mapped_column(Integer, default=30)
    language: Mapped[str] = mapped_column(String(40), default="iraqi_arabic")
    dialect: Mapped[str] = mapped_column(String(40), default="iraqi_professional")
    tone: Mapped[str] = mapped_column(String(40), default="ai_decide")
    target_audience: Mapped[str] = mapped_column(Text, default="")
    key_information: Mapped[str] = mapped_column(Text, default="")
    cta: Mapped[str] = mapped_column(Text, default="")
    production_mode: Mapped[str] = mapped_column(String(40), default="auto_smart")
    quality_level: Mapped[str] = mapped_column(String(40), default=QualityLevel.SMART_PREMIUM.value)
    voice_over_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # --- Lifecycle -------------------------------------------------------
    state: Mapped[str] = mapped_column(String(40), default=ProjectState.DRAFT.value, index=True)
    state_history: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(700), nullable=True)

    # --- Budget guard ----------------------------------------------------
    budget_limit_usd: Mapped[float] = mapped_column(Float, default=12.0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    actual_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    reserved_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)

    # --- Selections ------------------------------------------------------
    selected_concept_id: Mapped[Optional[str]] = mapped_column(GUID, nullable=True)
    selected_script_id: Mapped[Optional[str]] = mapped_column(GUID, nullable=True)
    selected_voice_profile_id: Mapped[Optional[str]] = mapped_column(GUID, nullable=True)
    voice_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    editing_style: Mapped[str] = mapped_column(String(40), default=EditingStyle.LUXURY_CLEAN.value)
    edit_settings: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    # --- Fidelity --------------------------------------------------------
    architecture_fidelity_lock: Mapped[bool] = mapped_column(Boolean, default=True)
    product_fidelity_lock: Mapped[bool] = mapped_column(Boolean, default=True)

    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicated_from_id: Mapped[Optional[str]] = mapped_column(GUID, nullable=True)

    analyses: Mapped[List["ProjectAnalysis"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    concepts: Mapped[List["Concept"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    scripts: Mapped[List["ScriptVersion"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    storyboards: Mapped[List["Storyboard"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    jobs: Mapped[List["GenerationJob"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    cost_entries: Mapped[List["CostEntry"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    approvals: Mapped[List["Approval"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    renders: Mapped[List["Render"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    qc_reports: Mapped[List["QCReport"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    exports: Mapped[List["Export"]] = relationship(back_populates="project", cascade="all, delete-orphan")

    @property
    def remaining_budget_usd(self) -> float:
        return round(self.budget_limit_usd - self.actual_cost_usd - self.reserved_cost_usd, 4)


class ProjectAnalysis(Base, TimestampMixin):
    __tablename__ = "project_analyses"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(GUID, ForeignKey("projects.id"))
    project: Mapped[Project] = relationship(back_populates="analyses")
    version: Mapped[int] = mapped_column(Integer, default=1)

    brief_interpretation: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    asset_analysis: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    creative_strategy: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    production_recommendation: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    recommended_mode: Mapped[str] = mapped_column(String(40), default="hybrid_reel")
    recommended_duration_sec: Mapped[int] = mapped_column(Integer, default=30)
    recommended_angle: Mapped[str] = mapped_column(String(40), default="emotional")
    recommended_voice_style: Mapped[str] = mapped_column(String(60), default="iraqi_professional")
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    readiness_score: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    director_notes: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)


class Concept(Base, TimestampMixin):
    __tablename__ = "concepts"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(GUID, ForeignKey("projects.id"))
    project: Mapped[Project] = relationship(back_populates="concepts")
    version: Mapped[int] = mapped_column(Integer, default=1)

    name: Mapped[str] = mapped_column(String(200))
    name_en: Mapped[str] = mapped_column(String(200), default="")
    angle: Mapped[str] = mapped_column(String(40), default="emotional")
    one_line_idea: Mapped[str] = mapped_column(Text, default="")
    hook: Mapped[str] = mapped_column(Text, default="")
    creative_direction: Mapped[str] = mapped_column(Text, default="")
    recommended_mode: Mapped[str] = mapped_column(String(40), default="hybrid_reel")
    recommended_voice: Mapped[str] = mapped_column(String(80), default="")
    visual_style: Mapped[str] = mapped_column(Text, default="")
    cta_style: Mapped[str] = mapped_column(Text, default="")
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    why_this_works: Mapped[str] = mapped_column(Text, default="")
    scores: Mapped[Dict[str, float]] = mapped_column(JSON, default=dict)
    score_total: Mapped[float] = mapped_column(Float, default=0.0)
    is_recommended: Mapped[bool] = mapped_column(Boolean, default=False)
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    is_alternative: Mapped[bool] = mapped_column(Boolean, default=False)


class ScriptVersion(Base, TimestampMixin):
    __tablename__ = "script_versions"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(GUID, ForeignKey("projects.id"))
    project: Mapped[Project] = relationship(back_populates="scripts")
    concept_id: Mapped[Optional[str]] = mapped_column(GUID, ForeignKey("concepts.id"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    variant: Mapped[str] = mapped_column(String(40), default="primary")  # primary|more_sales|more_emotional

    hook: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    cta: Mapped[str] = mapped_column(Text, default="")
    voice_over_text: Mapped[str] = mapped_column(Text, default="")
    on_screen_text: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    lines: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)  # timed VO lines
    dialect_preset: Mapped[str] = mapped_column(String(40), default="iraqi_professional")
    total_duration_sec: Mapped[float] = mapped_column(Float, default=30.0)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    critic_notes: Mapped[List[str]] = mapped_column(JSON, default=list)
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False)


class Storyboard(Base, TimestampMixin):
    __tablename__ = "storyboards"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(GUID, ForeignKey("projects.id"))
    project: Mapped[Project] = relationship(back_populates="storyboards")
    script_version_id: Mapped[Optional[str]] = mapped_column(GUID, ForeignKey("script_versions.id"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    total_duration_sec: Mapped[float] = mapped_column(Float, default=30.0)
    continuity_report: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    production_plan: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    scenes: Mapped[List["Scene"]] = relationship(
        back_populates="storyboard", cascade="all, delete-orphan", order_by="Scene.scene_number"
    )


class Scene(Base, TimestampMixin):
    __tablename__ = "scenes"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    storyboard_id: Mapped[str] = mapped_column(GUID, ForeignKey("storyboards.id"))
    storyboard: Mapped[Storyboard] = relationship(back_populates="scenes")

    scene_number: Mapped[int] = mapped_column(Integer, default=1)
    start_time: Mapped[float] = mapped_column(Float, default=0.0)
    end_time: Mapped[float] = mapped_column(Float, default=3.0)
    purpose: Mapped[str] = mapped_column(String(120), default="")
    voice_line: Mapped[str] = mapped_column(Text, default="")

    visual_source: Mapped[str] = mapped_column(String(40), default="existing_photo")
    selected_asset_id: Mapped[Optional[str]] = mapped_column(GUID, ForeignKey("assets.id"), nullable=True)
    visual_direction: Mapped[str] = mapped_column(Text, default="")
    camera_direction: Mapped[str] = mapped_column(String(160), default="")
    camera_movement: Mapped[str] = mapped_column(String(120), default="")
    lighting: Mapped[str] = mapped_column(String(160), default="")
    on_screen_text: Mapped[str] = mapped_column(Text, default="")
    text_animation: Mapped[str] = mapped_column(String(80), default="fade_up")
    music_instruction: Mapped[str] = mapped_column(String(200), default="")
    sfx_instruction: Mapped[str] = mapped_column(String(200), default="")
    transition: Mapped[str] = mapped_column(String(80), default="cut")

    production_method: Mapped[str] = mapped_column(String(40), default="original_photo")
    recommended_model: Mapped[str] = mapped_column(String(80), default="mock-image-v1")
    recommended_provider: Mapped[str] = mapped_column(String(60), default="mock")
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    actual_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    quality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    quality_breakdown: Mapped[Dict[str, float]] = mapped_column(JSON, default=dict)

    status: Mapped[str] = mapped_column(String(30), default="ready")
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    is_hook: Mapped[bool] = mapped_column(Boolean, default=False)
    is_hero: Mapped[bool] = mapped_column(Boolean, default=False)
    priority: Mapped[int] = mapped_column(Integer, default=50)

    keyframe_url: Mapped[Optional[str]] = mapped_column(String(700), nullable=True)
    keyframe_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    output_url: Mapped[Optional[str]] = mapped_column(String(700), nullable=True)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(700), nullable=True)
    compiled_prompt: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    generation_attempts: Mapped[int] = mapped_column(Integer, default=0)
    #: Video-remix instructions when the scene comes from user footage.
    remix_ops: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)


class GenerationJob(Base, TimestampMixin):
    __tablename__ = "generation_jobs"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(GUID, ForeignKey("projects.id"))
    project: Mapped[Project] = relationship(back_populates="jobs")
    scene_id: Mapped[Optional[str]] = mapped_column(GUID, ForeignKey("scenes.id"), nullable=True)

    job_type: Mapped[str] = mapped_column(String(40), default="image_generation")
    status: Mapped[str] = mapped_column(String(30), default=JobStatus.QUEUED.value)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    progress_label: Mapped[str] = mapped_column(String(160), default="")
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    actual_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    runs: Mapped[List["ProviderRun"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class ProviderRun(Base, TimestampMixin):
    __tablename__ = "provider_runs"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    job_id: Mapped[str] = mapped_column(GUID, ForeignKey("generation_jobs.id"))
    job: Mapped[GenerationJob] = relationship(back_populates="runs")

    provider: Mapped[str] = mapped_column(String(60), default="mock")
    model: Mapped[str] = mapped_column(String(80), default="mock-v1")
    operation: Mapped[str] = mapped_column(String(60), default="generate")
    is_mock: Mapped[bool] = mapped_column(Boolean, default=True)
    request_prompt: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    response_meta: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    quality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)


class Render(Base, TimestampMixin):
    __tablename__ = "renders"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(GUID, ForeignKey("projects.id"))
    project: Mapped[Project] = relationship(back_populates="renders")
    version: Mapped[int] = mapped_column(Integer, default=1)
    editing_style: Mapped[str] = mapped_column(String(40), default="luxury_clean")
    settings: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    timeline: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    url: Mapped[Optional[str]] = mapped_column(String(700), nullable=True)
    poster_url: Mapped[Optional[str]] = mapped_column(String(700), nullable=True)
    duration_sec: Mapped[float] = mapped_column(Float, default=30.0)
    width: Mapped[int] = mapped_column(Integer, default=1080)
    height: Mapped[int] = mapped_column(Integer, default=1920)
    status: Mapped[str] = mapped_column(String(30), default="completed")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class QCReport(Base, TimestampMixin):
    __tablename__ = "qc_reports"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(GUID, ForeignKey("projects.id"))
    project: Mapped[Project] = relationship(back_populates="qc_reports")
    render_id: Mapped[Optional[str]] = mapped_column(GUID, ForeignKey("renders.id"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)

    scores: Mapped[Dict[str, float]] = mapped_column(JSON, default=dict)
    total_score: Mapped[float] = mapped_column(Float, default=0.0)
    verdict: Mapped[str] = mapped_column(String(30), default="approved")  # approved|review|fix_required
    critical_issues: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    recommendations: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    checks: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    ready_to_export: Mapped[bool] = mapped_column(Boolean, default=False)


class Export(Base, TimestampMixin):
    __tablename__ = "exports"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(GUID, ForeignKey("projects.id"))
    project: Mapped[Project] = relationship(back_populates="exports")
    render_id: Mapped[Optional[str]] = mapped_column(GUID, ForeignKey("renders.id"), nullable=True)

    variant: Mapped[str] = mapped_column(String(40), default="master")
    aspect_ratio: Mapped[str] = mapped_column(String(10), default="9:16")
    width: Mapped[int] = mapped_column(Integer, default=1080)
    height: Mapped[int] = mapped_column(Integer, default=1920)
    filename: Mapped[str] = mapped_column(String(300), default="")
    url: Mapped[Optional[str]] = mapped_column(String(700), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    codec: Mapped[str] = mapped_column(String(30), default="h264")
    status: Mapped[str] = mapped_column(String(30), default="ready")


class Approval(Base, TimestampMixin):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(GUID, ForeignKey("projects.id"))
    project: Mapped[Project] = relationship(back_populates="approvals")

    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[Optional[str]] = mapped_column(GUID, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default=ApprovalStatus.PENDING.value)
    approved_by_id: Mapped[Optional[str]] = mapped_column(GUID, ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    invalidated_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class CostEntry(Base, TimestampMixin):
    __tablename__ = "cost_entries"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(GUID, ForeignKey("projects.id"))
    project: Mapped[Project] = relationship(back_populates="cost_entries")
    scene_id: Mapped[Optional[str]] = mapped_column(GUID, ForeignKey("scenes.id"), nullable=True)
    job_id: Mapped[Optional[str]] = mapped_column(GUID, ForeignKey("generation_jobs.id"), nullable=True)

    provider: Mapped[str] = mapped_column(String(60), default="mock")
    model: Mapped[str] = mapped_column(String(80), default="mock-v1")
    operation: Mapped[str] = mapped_column(String(60), default="generate")
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    actual_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    status: Mapped[str] = mapped_column(String(20), default=CostStatus.ESTIMATED.value)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str] = mapped_column(String(300), default="")


class PerformanceMetric(Base, TimestampMixin):
    """Future performance-feedback loop (no external integrations in V1)."""

    __tablename__ = "performance_metrics"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(GUID, ForeignKey("projects.id"))
    platform: Mapped[str] = mapped_column(String(40), default="instagram_reels")
    views: Mapped[int] = mapped_column(Integer, default=0)
    watch_time_sec: Mapped[float] = mapped_column(Float, default=0.0)
    ctr: Mapped[float] = mapped_column(Float, default=0.0)
    leads: Mapped[int] = mapped_column(Integer, default=0)
    cost_per_lead: Mapped[float] = mapped_column(Float, default=0.0)
    conversion_rate: Mapped[float] = mapped_column(Float, default=0.0)
    meta: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
