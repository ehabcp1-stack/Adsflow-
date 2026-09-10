"""Voice preview, selection and locking.

Once a voice is locked the storyboard uses its timing.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.models import BrandKit, Project, ScriptVersion, VoiceProfile
from app.providers.pricing import estimate_voice_cost
from app.providers.registry import get_voice
from app.services.dialect import build_pronunciation_guide, estimate_speech_seconds


def ensure_demo_voices(db: Session, organization_id: Optional[str] = None) -> List[VoiceProfile]:
    provider = get_voice()
    existing = db.query(VoiceProfile).all()
    if existing:
        return existing
    created: List[VoiceProfile] = []
    for voice in provider.list_voices():
        profile = VoiceProfile(
            organization_id=organization_id,
            name=voice["name"],
            name_ar=voice.get("name_ar", ""),
            provider=voice.get("provider", "mock"),
            provider_voice_id=voice["id"],
            gender=voice.get("gender", "male"),
            dialect=voice.get("dialect", "iraqi_professional"),
            style=voice.get("style", "professional"),
            is_demo=voice.get("is_demo", True),
        )
        db.add(profile)
        created.append(profile)
    db.flush()
    return created


def preview_voice(
    db: Session,
    *,
    profile: VoiceProfile,
    text: str,
    speed: float = 1.0,
    energy: float = 0.6,
    emotion: float = 0.5,
) -> Dict[str, Any]:
    provider = get_voice(profile.provider)
    result = provider.synthesize(
        text=text, voice_id=profile.provider_voice_id, speed=speed, energy=energy, emotion=emotion
    )
    return {
        "ok": result.ok,
        "url": result.url,
        "provider": result.provider,
        "is_mock": result.is_mock,
        "duration_sec": result.data.get("duration_sec", estimate_speech_seconds(text, speed)),
        "estimated_cost_usd": estimate_voice_cost(len(text)),
        "error": result.error,
    }


def select_voice(db: Session, project: Project, profile_id: str, *, lock: bool = False) -> VoiceProfile:
    profile = db.get(VoiceProfile, profile_id)
    if not profile:
        raise NotFound("Voice profile not found.", "الصوت غير موجود.")
    project.selected_voice_profile_id = profile.id
    project.voice_locked = lock or project.voice_locked
    db.flush()
    return profile


def voice_timing(db: Session, project: Project, script: ScriptVersion) -> List[Dict[str, Any]]:
    """Timing used by the storyboard once a voice is locked."""
    profile = db.get(VoiceProfile, project.selected_voice_profile_id) if project.selected_voice_profile_id else None
    speed = profile.speed if profile else 1.0
    timings: List[Dict[str, Any]] = []
    cursor = 0.0
    raw = [max(estimate_speech_seconds(line["voice_line"], speed), 1.2) for line in (script.lines or [])] or [1.0]
    scale = script.total_duration_sec / sum(raw)
    for line, seconds in zip(script.lines or [], raw):
        length = round(seconds * scale, 2)
        timings.append(
            {
                "index": line.get("index"),
                "role": line.get("role"),
                "voice_line": line.get("voice_line"),
                "start": round(cursor, 2),
                "end": round(min(cursor + length, script.total_duration_sec), 2),
            }
        )
        cursor += length
    if timings:
        timings[-1]["end"] = script.total_duration_sec
    return timings


def pronunciation_for_project(db: Session, project: Project) -> Dict[str, Any]:
    brand = db.get(BrandKit, project.brand_kit_id) if project.brand_kit_id else None
    numbers = []
    for token in (project.key_information or "").split():
        digits = "".join(ch for ch in token if ch.isdigit())
        if digits and len(digits) <= 6:
            numbers.append(int(digits))
    return build_pronunciation_guide(
        project_name=project.name,
        brand_name=brand.name if brand else None,
        phone=brand.phone if brand else None,
        numbers=numbers[:6],
        overrides=(brand.pronunciation_rules if brand else {}) or {},
    )


def voice_payload(profile: VoiceProfile) -> Dict[str, Any]:
    return {
        "id": profile.id,
        "name": profile.name,
        "name_ar": profile.name_ar,
        "provider": profile.provider,
        "gender": profile.gender,
        "dialect": profile.dialect,
        "style": profile.style,
        "speed": profile.speed,
        "energy": profile.energy,
        "emotion": profile.emotion,
        "sample_url": profile.sample_url,
        "is_demo": profile.is_demo,
    }
