"""Official AdFlow AI enumerations. These are product rules — do not rename casually."""
from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


# --------------------------------------------------------------------------
# Project lifecycle
# --------------------------------------------------------------------------
class ProjectState(StrEnum):
    DRAFT = "DRAFT"
    ANALYZING = "ANALYZING"
    ANALYSIS_READY = "ANALYSIS_READY"
    CONCEPT_REVIEW = "CONCEPT_REVIEW"
    CONCEPT_APPROVED = "CONCEPT_APPROVED"
    SCRIPT_REVIEW = "SCRIPT_REVIEW"
    SCRIPT_APPROVED = "SCRIPT_APPROVED"
    STORYBOARD_REVIEW = "STORYBOARD_REVIEW"
    STORYBOARD_APPROVED = "STORYBOARD_APPROVED"
    PRODUCTION_READY = "PRODUCTION_READY"
    GENERATING = "GENERATING"
    EDITING = "EDITING"
    QC_REVIEW = "QC_REVIEW"
    FINAL_APPROVAL = "FINAL_APPROVAL"
    EXPORTED = "EXPORTED"
    # supporting
    PAUSED = "PAUSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class WorkflowStage(StrEnum):
    BRIEF = "brief"
    ANALYZE = "analyze"
    CONCEPTS = "concepts"
    SCRIPT = "script"
    VOICE = "voice"
    STORYBOARD = "storyboard"
    PRODUCTION = "production"
    EDIT = "edit"
    QC = "qc"
    EXPORT = "export"


# --------------------------------------------------------------------------
# Brief vocabulary
# --------------------------------------------------------------------------
class CampaignGoal(StrEnum):
    LEADS = "leads"
    SALES = "sales"
    AWARENESS = "awareness"
    OFFER = "offer"
    LAUNCH = "launch"


class Platform(StrEnum):
    INSTAGRAM_REELS = "instagram_reels"
    FACEBOOK_REELS = "facebook_reels"
    TIKTOK = "tiktok"
    MULTI = "multi"


class Language(StrEnum):
    IRAQI_ARABIC = "iraqi_arabic"
    MSA = "msa"
    ENGLISH = "english"


class Dialect(StrEnum):
    IRAQI_PROFESSIONAL = "iraqi_professional"
    IRAQI_LUXURY = "iraqi_luxury"
    IRAQI_EMOTIONAL = "iraqi_emotional"
    IRAQI_DIRECT_SALES = "iraqi_direct_sales"
    IRAQI_FRIENDLY = "iraqi_friendly"
    IRAQI_YOUTH = "iraqi_youth"
    NONE = "none"


class Tone(StrEnum):
    AI_DECIDE = "ai_decide"
    LUXURY = "luxury"
    EMOTIONAL = "emotional"
    DIRECT = "direct"
    FRIENDLY = "friendly"
    PROFESSIONAL = "professional"


class ProductionMode(StrEnum):
    AUTO_SMART = "auto_smart"
    PHOTO_VOICE_REEL = "photo_voice_reel"
    VIDEO_REMIX_REEL = "video_remix_reel"
    HYBRID_REEL = "hybrid_reel"
    FULL_AI_REEL = "full_ai_reel"
    OFFER_INFO_REEL = "offer_info_reel"


class QualityLevel(StrEnum):
    ECONOMY = "economy"
    SMART_PREMIUM = "smart_premium"
    MAXIMUM_QUALITY = "maximum_quality"


class StrategicAngle(StrEnum):
    EMOTIONAL = "emotional"
    LUXURY = "luxury"
    DIRECT_RESPONSE = "direct_response"
    LIFESTYLE = "lifestyle"
    INVESTMENT = "investment"
    INFORMATION_OFFER = "information_offer"
    UGC_LIKE = "ugc_like"
    AUTHORITY_TRUST = "authority_trust"


# --------------------------------------------------------------------------
# Assets & scenes
# --------------------------------------------------------------------------
class AssetKind(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    LOGO = "logo"
    REFERENCE = "reference"
    AUDIO = "audio"
    RENDER = "render"


class SceneSource(StrEnum):
    EXISTING_PHOTO = "existing_photo"
    EXISTING_VIDEO = "existing_video"
    AI_IMAGE = "ai_image"
    AI_VIDEO = "ai_video"
    MOTION_GRAPHICS = "motion_graphics"


class ProductionMethod(StrEnum):
    ORIGINAL_VIDEO = "original_video"
    ORIGINAL_PHOTO = "original_photo"
    PHOTO_MOTION = "photo_motion"
    AI_IMAGE = "ai_image"
    AI_VIDEO = "ai_video"
    MOTION_GRAPHICS = "motion_graphics"


#: Official cost-first priority order. Lower index = try first.
SCENE_SOURCE_PRIORITY = [
    ProductionMethod.ORIGINAL_VIDEO,
    ProductionMethod.ORIGINAL_PHOTO,
    ProductionMethod.PHOTO_MOTION,
    ProductionMethod.AI_IMAGE,
    ProductionMethod.AI_VIDEO,
]


class SceneStatus(StrEnum):
    READY = "ready"
    GENERATING = "generating"
    REVIEWING = "reviewing"
    APPROVED = "approved"
    LOCKED = "locked"
    FAILED = "failed"


class JobType(StrEnum):
    IMAGE_GENERATION = "image_generation"
    #: The still that an AI-video scene is conditioned on. Generated and
    #: approved before any video spend — see services/production.py.
    KEYFRAME_GENERATION = "keyframe_generation"
    VIDEO_GENERATION = "video_generation"
    VOICE_GENERATION = "voice_generation"
    MUSIC_GENERATION = "music_generation"
    VIDEO_TRANSFORM = "video_transform"
    PHOTO_MOTION = "photo_motion"
    CAPTION_RENDER = "caption_render"
    FINAL_RENDER = "final_render"
    QC_CHECK = "qc_check"
    #: The four writing stages. Each is a chain of model calls that outlives an
    #: HTTP connection, so none of them may run inside a request — see
    #: services/stage_jobs.py.
    ANALYSIS = "analysis"
    CONCEPTS = "concepts"
    SCRIPT = "script"
    STORYBOARD = "storyboard"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


class ApprovalEntity(StrEnum):
    ANALYSIS = "analysis"
    CONCEPT = "concept"
    SCRIPT = "script"
    VOICE = "voice"
    STORYBOARD = "storyboard"
    PRODUCTION_PLAN = "production_plan"
    BUDGET = "budget"
    FINAL = "final"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    INVALIDATED = "invalidated"


class EditingStyle(StrEnum):
    LUXURY_CLEAN = "luxury_clean"
    FAST_SOCIAL = "fast_social"
    EMOTIONAL_CINEMATIC = "emotional_cinematic"
    DIRECT_SALES = "direct_sales"
    MINIMAL_PREMIUM = "minimal_premium"


class ExportVariant(StrEnum):
    MASTER = "master"
    WITH_CAPTIONS = "with_captions"
    WITHOUT_CAPTIONS = "without_captions"
    WITHOUT_MUSIC = "without_music"
    VOICE_ONLY = "voice_only"
    CLEAN_NO_LOGO = "clean_no_logo"
    BRANDED = "branded"
    THUMBNAIL = "thumbnail"


class AspectRatio(StrEnum):
    VERTICAL_9_16 = "9:16"
    SQUARE_1_1 = "1:1"
    PORTRAIT_4_5 = "4:5"
    LANDSCAPE_16_9 = "16:9"


class CostStatus(StrEnum):
    ESTIMATED = "estimated"
    RESERVED = "reserved"
    ACTUAL = "actual"
    REFUNDED = "refunded"
