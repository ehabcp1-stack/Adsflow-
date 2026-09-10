"""Request/response schemas (Pydantic v2)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: Dict[str, Any]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: str = "real_estate"
    goal: str = "leads"
    platform: str = "instagram_reels"
    duration_sec: int = 30
    language: str = "iraqi_arabic"
    dialect: str = "iraqi_professional"
    tone: str = "ai_decide"
    target_audience: str = ""
    key_information: str = ""
    cta: str = ""
    production_mode: str = "auto_smart"
    quality_level: str = "smart_premium"
    voice_over_enabled: bool = True
    brand_kit_id: Optional[str] = None
    budget_limit_usd: Optional[float] = None
    asset_ids: List[str] = Field(default_factory=list)


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    goal: Optional[str] = None
    platform: Optional[str] = None
    duration_sec: Optional[int] = None
    language: Optional[str] = None
    dialect: Optional[str] = None
    tone: Optional[str] = None
    target_audience: Optional[str] = None
    key_information: Optional[str] = None
    cta: Optional[str] = None
    production_mode: Optional[str] = None
    quality_level: Optional[str] = None
    voice_over_enabled: Optional[bool] = None
    brand_kit_id: Optional[str] = None
    budget_limit_usd: Optional[float] = None
    editing_style: Optional[str] = None
    architecture_fidelity_lock: Optional[bool] = None
    product_fidelity_lock: Optional[bool] = None


class ApproveRequest(BaseModel):
    entity_id: Optional[str] = None
    notes: str = ""


class SelectRequest(BaseModel):
    id: str


class RefineRequest(BaseModel):
    action: str
    new_cta: Optional[str] = None


class ScriptLinesUpdate(BaseModel):
    lines: List[Dict[str, Any]]


class VoicePreviewRequest(BaseModel):
    voice_profile_id: str
    text: Optional[str] = None
    speed: float = 1.0
    energy: float = 0.6
    emotion: float = 0.5


class VoiceSelectRequest(BaseModel):
    voice_profile_id: str
    lock: bool = False
    speed: Optional[float] = None
    energy: Optional[float] = None
    emotion: Optional[float] = None


class SceneUpdate(BaseModel):
    changes: Dict[str, Any] = Field(default_factory=dict)


class LockRequest(BaseModel):
    locked: bool = True


class EditSettingsUpdate(BaseModel):
    changes: Dict[str, Any] = Field(default_factory=dict)


class ExportRequest(BaseModel):
    variant: str = "master"
    aspect_ratio: str = "9:16"
    force: bool = False


class BudgetUpdate(BaseModel):
    budget_limit_usd: float


class BrandKitPayload(BaseModel):
    name: str
    name_ar: Optional[str] = None
    logo_url: Optional[str] = None
    primary_color: str = "#0F172A"
    secondary_color: str = "#2563EB"
    accent_color: str = "#1D4ED8"
    font_arabic: str = "Cairo"
    font_latin: str = "Inter"
    caption_style: Dict[str, Any] = Field(default_factory=dict)
    editing_style: str = "luxury_clean"
    voice_profile_id: Optional[str] = None
    music_profile: Dict[str, Any] = Field(default_factory=dict)
    cta_template: Dict[str, Any] = Field(default_factory=dict)
    end_screen_template: Dict[str, Any] = Field(default_factory=dict)
    phone: Optional[str] = None
    website: Optional[str] = None
    social_handles: Dict[str, Any] = Field(default_factory=dict)
    pronunciation_rules: Dict[str, Any] = Field(default_factory=dict)
    forbidden_phrases: List[str] = Field(default_factory=list)
    preferred_phrases: List[str] = Field(default_factory=list)
    is_default: bool = False


class AssetRegister(BaseModel):
    """Register an asset by URL (used by the demo seeder and remote media)."""

    kind: str = "image"
    filename: str = ""
    url: str
    thumbnail_url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    duration_sec: Optional[float] = None
    project_id: Optional[str] = None
    is_project_reference: bool = False
    tags: List[str] = Field(default_factory=list)


class UserSettingsUpdate(BaseModel):
    locale: Optional[str] = None
    director_mode: Optional[bool] = None
    full_name: Optional[str] = None
