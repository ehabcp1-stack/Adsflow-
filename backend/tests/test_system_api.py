"""`/system/*` — the status surface behind Settings → Providers.

The load-bearing test here is `test_provider_status_never_leaks_a_secret`:
this endpoint describes credential *configuration*, and a regression that
serialises a `ModelSpec`/settings object wholesale would quietly publish live
API keys to every browser that opens Settings.
"""
from __future__ import annotations

import json

import pytest

from app.core.config import settings
from app.providers import catalog

API = "/api/v1"

#: Distinctive enough that a substring match cannot false-positive.
SENTINEL = "sk-do-not-leak-3f9a1c7b5e2d4806"


@pytest.fixture
def configured_keys(monkeypatch):
    """Pretend every provider key is set, so a leak has something to leak."""
    names = sorted({s.requires_key for s in catalog.all_specs() if s.requires_key})
    for index, name in enumerate(names):
        monkeypatch.setattr(settings, name, f"{SENTINEL}-{index}", raising=False)
    return names


def test_providers_grouped_by_capability(client):
    data = client.get(f"{API}/system/providers").json()

    assert data["force_mock"] is True
    assert data["runtime_mode"] == "mock"
    assert data["kinds"] == ["llm", "image", "video", "voice", "music"]

    for kind in data["kinds"]:
        rows = data["by_kind"][kind]
        assert rows, f"{kind} has no models"
        assert all(row["kind"] == kind for row in rows)
        # Fallback order is what the UI prints, so it must arrive sorted.
        assert rows == sorted(rows, key=lambda r: (r["fallback_priority"], r["model_id"]))

    video = data["by_kind"]["video"]
    mock = next(row for row in video if row["provider"] == "mock")
    assert mock["is_mock"] is True
    assert mock["configured"] is True          # mock needs no key
    assert mock["requires_key"] is None
    assert mock["cost_per_unit"] == 0.0
    # FORCE_MOCK_PROVIDERS=true in tests, so mock is the resolved default.
    assert mock["is_default"] is True

    veo = next(row for row in video if row["model_id"].startswith("veo"))
    assert veo["requires_key"] == "VEO_API_KEY"
    assert veo["is_mock"] is False
    assert veo["cost_unit"] == "per_second" and veo["cost_per_unit"] > 0
    assert veo["quality_tier"] in catalog.QUALITY_TIERS
    assert veo["latency_tier"] in catalog.LATENCY_TIERS
    assert isinstance(veo["capabilities"], list) and veo["capabilities"]

    assert data["totals"]["models"] == sum(len(rows) for rows in data["by_kind"].values())


def test_every_model_row_carries_the_fields_the_ui_renders(client):
    data = client.get(f"{API}/system/providers").json()
    required = {
        "kind", "provider", "model_id", "display_name", "configured", "enabled",
        "healthy", "is_mock", "is_default", "fallback_priority", "quality_tier",
        "latency_tier", "cost_unit", "cost_per_unit", "capabilities",
        "requires_key", "notes_ar", "notes_en",
    }
    for rows in data["by_kind"].values():
        for row in rows:
            assert required <= set(row), f"{row['model_id']} missing {required - set(row)}"


def test_provider_status_never_leaks_a_secret(client, configured_keys):
    """No response from /system/* may contain a key's value — only its name."""
    assert configured_keys, "no provider keys are declared in the catalog"

    for path in ("/system/providers", "/system/pricing", "/system/health"):
        response = client.get(f"{API}{path}")
        assert response.status_code == 200
        body = json.dumps(response.json(), ensure_ascii=False)
        assert SENTINEL not in body, f"{path} leaked a configured provider key"
        for name in configured_keys:
            assert getattr(settings, name) not in body

    # The *names* must still be reported, otherwise the UI cannot tell the
    # operator which variable to set.
    providers = client.get(f"{API}/system/providers").json()
    reported = {
        row["requires_key"]
        for rows in providers["by_kind"].values()
        for row in rows
        if row["requires_key"]
    }
    assert reported == set(configured_keys)


def test_configured_flips_with_the_key_being_present(client, monkeypatch):
    def elevenlabs():
        rows = client.get(f"{API}/system/providers").json()["by_kind"]["voice"]
        return next(row for row in rows if row["provider"] == "elevenlabs")

    monkeypatch.setattr(settings, "ELEVENLABS_API_KEY", None, raising=False)
    assert elevenlabs()["configured"] is False
    assert elevenlabs()["key_present"] is False

    monkeypatch.setattr(settings, "ELEVENLABS_API_KEY", f"{SENTINEL}-voice", raising=False)
    row = elevenlabs()
    assert row["configured"] is True and row["key_present"] is True
    # Still not the default: FORCE_MOCK_PROVIDERS keeps mock resolved.
    assert row["is_default"] is False


def test_pricing_lists_every_catalog_model_without_secrets(client):
    pricing = client.get(f"{API}/system/pricing").json()
    assert set(pricing) == {"by_kind", "method_base_cost", "flat_costs"}
    for kind in ("llm", "image", "video", "voice", "music"):
        assert pricing["by_kind"][kind]
        for row in pricing["by_kind"][kind]:
            assert {"provider_id", "model_id", "cost_unit", "cost_per_unit"} <= set(row)
    assert pricing["method_base_cost"]["ai_video"] > pricing["method_base_cost"]["ai_image"]
    assert pricing["method_base_cost"]["original_photo"] == 0.0


def test_health_reports_runtime_facts(client):
    health = client.get(f"{API}/system/health").json()
    assert health["app"] == settings.APP_NAME
    assert health["env"] == settings.ENV
    assert health["runtime_mode"] == "mock"
    assert health["force_mock_providers"] is True
    assert health["storage_backend"] == settings.STORAGE_BACKEND
    assert health["job_backend"] == settings.JOB_BACKEND
    assert isinstance(health["ffmpeg_available"], bool)
    assert isinstance(health["ffprobe_available"], bool)
    assert isinstance(health["local_render_enabled"], bool)
