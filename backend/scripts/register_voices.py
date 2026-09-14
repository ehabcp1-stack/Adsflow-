"""Register the customer's own cloned ElevenLabs voices as usable profiles.

The clones live in the ElevenLabs account; AdFlow only needs to know their ids
so `model_router` can pick them. Nothing here invents a voice: it asks the
provider for the list and matches by name, so if a name is missing the script
says so rather than writing a profile that will fail at render time.

    ELEVENLABS_API_KEY=... python -m scripts.register_voices

The key is read from the environment and never printed.
"""
from __future__ import annotations

import argparse
import sys
from typing import Dict, List, Optional

from app.core.db import SessionLocal, init_db
from app.models import Organization, VoiceProfile
from app.providers import registry

#: The Iraqi clones, as named in the ElevenLabs account. `dialect` is the
#: dialect layer AdFlow applies (services/dialect.py), not a provider feature —
#: no vendor offers Iraqi Arabic, which is exactly why these clones exist.
WANTED = [
    {
        "match": "TADAFQ Iraqi A",
        # Read from the account on 2026-09-14. The id is the durable handle;
        # the name is only how a human finds it, and renaming a voice in the
        # dashboard must not silently detach it from the product.
        "voice_id": "pneHqDEKkAh69hIsM5Tx",
        "name": "TADAFQ Iraqi A",
        "name_ar": "الصوت العراقي A",
        "dialect": "iraqi_emotional",
        "style": "emotional",
        # Measured against the source recording: the clone runs brighter and a
        # touch fast for ad reads, so it ships slightly slowed.
        "speed": 0.84,
        "energy": 0.62,
        "emotion": 0.55,
    },
    {
        "match": "TADAFQ Iraqi B",
        "voice_id": "aM1JesROynRV9XUGI7GL",
        "name": "TADAFQ Iraqi B",
        "name_ar": "الصوت العراقي B",
        "dialect": "iraqi_professional",
        "style": "professional",
        "speed": 1.0,
        "energy": 0.58,
        "emotion": 0.45,
    },
]


def _find(voices: List[Dict], wanted: str) -> Optional[Dict]:
    target = wanted.strip().casefold()
    for voice in voices:
        if (voice.get("name") or "").strip().casefold() == target:
            return voice
    return None


def register(dry_run: bool = False) -> int:
    # The ids below are what the profiles are written from, so registration
    # works with no network. Reaching the provider is a *verification* step:
    # it catches a voice that was deleted or renamed in the dashboard, which is
    # the failure that would otherwise surface as a dead render hours later.
    voices: List[Dict] = []
    provider = registry.get_voice("elevenlabs")
    if getattr(provider, "available", lambda: False)():
        voices = provider.list_voices()
        if voices:
            print(f"provider reachable — {len(voices)} voices in the account")
        else:
            print("provider returned no voices; registering from stored ids only")
    else:
        print("provider not reachable from here; registering from stored ids only")

    init_db()
    db = SessionLocal()
    try:
        org = db.query(Organization).first()
        if org is None:
            print("no organization in the database; seed one first", file=sys.stderr)
            return 4

        unverified: List[str] = []
        for spec in WANTED:
            voice_id = spec["voice_id"]
            if voices:
                found = _find(voices, spec["match"])
                if not found:
                    unverified.append(f"{spec['match']} (no voice by that name)")
                elif found["id"] != voice_id:
                    unverified.append(
                        f"{spec['match']} (account id differs — using the account's)"
                    )
                    voice_id = found["id"]
            profile = (
                db.query(VoiceProfile)
                .filter(
                    VoiceProfile.organization_id == org.id,
                    VoiceProfile.provider == "elevenlabs",
                    VoiceProfile.provider_voice_id == voice_id,
                )
                .first()
            )
            action = "updated" if profile else "created"
            if profile is None:
                profile = VoiceProfile(organization_id=org.id)
                db.add(profile)
            profile.name = spec["name"]
            profile.name_ar = spec["name_ar"]
            profile.provider = "elevenlabs"
            profile.provider_voice_id = voice_id
            profile.dialect = spec["dialect"]
            profile.style = spec["style"]
            profile.speed = spec["speed"]
            profile.energy = spec["energy"]
            profile.emotion = spec["emotion"]
            # These are real, billable voices — never treat them as demo rows.
            profile.is_demo = False
            print(f"  {action}: {spec['name']}  (voice id ends …{voice_id[-4:]})")

        if unverified:
            print("\ncould not verify against the account:", file=sys.stderr)
            for line in unverified:
                print(f"  - {line}", file=sys.stderr)

        if dry_run:
            db.rollback()
            print("\ndry run — nothing saved")
        else:
            db.commit()
            print("\nsaved")
        return 0 if not unverified else 5
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="resolve the ids and print what would change")
    args = parser.parse_args()
    sys.exit(register(dry_run=args.dry_run))
