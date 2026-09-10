"""Users, organizations, brand kits, voice profiles, assets."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import GUID, Base, TimestampMixin, new_uuid


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(160))
    name_ar: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    parent_brand: Mapped[str] = mapped_column(String(80), default="TADAFQ")
    monthly_budget_usd: Mapped[float] = mapped_column(Float, default=50.0)

    users: Mapped[List["User"]] = relationship(back_populates="organization")
    projects: Mapped[List["Project"]] = relationship(back_populates="organization")  # noqa: F821
    brand_kits: Mapped[List["BrandKit"]] = relationship(back_populates="organization")


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160), default="")
    hashed_password: Mapped[str] = mapped_column(String(255), default="")
    role: Mapped[str] = mapped_column(String(40), default="owner")
    locale: Mapped[str] = mapped_column(String(8), default="ar")
    director_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    organization_id: Mapped[str] = mapped_column(GUID, ForeignKey("organizations.id"))
    organization: Mapped[Organization] = relationship(back_populates="users")


class BrandKit(Base, TimestampMixin):
    __tablename__ = "brand_kits"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(GUID, ForeignKey("organizations.id"))
    organization: Mapped[Organization] = relationship(back_populates="brand_kits")

    name: Mapped[str] = mapped_column(String(160))
    name_ar: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    logo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    primary_color: Mapped[str] = mapped_column(String(16), default="#0F172A")
    secondary_color: Mapped[str] = mapped_column(String(16), default="#2563EB")
    accent_color: Mapped[str] = mapped_column(String(16), default="#1D4ED8")
    font_arabic: Mapped[str] = mapped_column(String(80), default="Cairo")
    font_latin: Mapped[str] = mapped_column(String(80), default="Inter")

    caption_style: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    editing_style: Mapped[str] = mapped_column(String(40), default="luxury_clean")
    voice_profile_id: Mapped[Optional[str]] = mapped_column(GUID, nullable=True)
    music_profile: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    cta_template: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    end_screen_template: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    phone: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    website: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    social_handles: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    # Dialect / pronunciation guardrails (Iraqi Arabic engine)
    pronunciation_rules: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    forbidden_phrases: Mapped[List[str]] = mapped_column(JSON, default=list)
    preferred_phrases: Mapped[List[str]] = mapped_column(JSON, default=list)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class VoiceProfile(Base, TimestampMixin):
    __tablename__ = "voice_profiles"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    organization_id: Mapped[Optional[str]] = mapped_column(GUID, ForeignKey("organizations.id"), nullable=True)

    name: Mapped[str] = mapped_column(String(120))
    name_ar: Mapped[str] = mapped_column(String(120), default="")
    provider: Mapped[str] = mapped_column(String(60), default="mock")
    provider_voice_id: Mapped[str] = mapped_column(String(120), default="mock-voice")
    gender: Mapped[str] = mapped_column(String(20), default="male")
    dialect: Mapped[str] = mapped_column(String(40), default="iraqi_professional")
    style: Mapped[str] = mapped_column(String(40), default="professional")
    speed: Mapped[float] = mapped_column(Float, default=1.0)
    energy: Mapped[float] = mapped_column(Float, default=0.6)
    emotion: Mapped[float] = mapped_column(Float, default=0.5)
    sample_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    cost_per_1k_chars: Mapped[float] = mapped_column(Float, default=0.18)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True)


class Asset(Base, TimestampMixin):
    """Uploaded or generated media. Binaries never live in Postgres."""

    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(GUID, ForeignKey("organizations.id"))
    project_id: Mapped[Optional[str]] = mapped_column(GUID, ForeignKey("projects.id"), nullable=True)

    kind: Mapped[str] = mapped_column(String(20), default="image")
    filename: Mapped[str] = mapped_column(String(255), default="")
    storage_key: Mapped[str] = mapped_column(String(500), default="")
    url: Mapped[str] = mapped_column(String(700), default="")
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(700), nullable=True)
    mime_type: Mapped[str] = mapped_column(String(120), default="image/jpeg")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)

    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration_sec: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    orientation: Mapped[str] = mapped_column(String(20), default="landscape")

    #: Structured output of the Asset Analyzer (see services/analysis.py)
    analysis: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    quality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hero_potential: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    usable: Mapped[bool] = mapped_column(Boolean, default=True)
    category: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    suggested_use: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Real-estate fidelity: source-of-truth reference for the real project.
    is_project_reference: Mapped[bool] = mapped_column(Boolean, default=False)
    tags: Mapped[List[str]] = mapped_column(JSON, default=list)
