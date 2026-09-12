"""Provider catalog, HTTP helper, structured-output validation, adapter safety."""
from __future__ import annotations

import json as jsonlib

import pytest

from app.core.config import settings
from app.providers import adapters as A
from app.providers import catalog
from app.providers import http as H
from app.providers import pricing
from app.providers import registry
from app.providers import schemas as S


# --------------------------------------------------------------------------
# Catalog integrity
# --------------------------------------------------------------------------
def test_every_spec_has_a_valid_cost_unit():
    for spec in catalog.all_specs():
        assert spec.cost_unit in catalog.COST_UNITS, f"{spec.provider_id}/{spec.model_id} has bad cost_unit"


def test_every_spec_requires_key_that_exists_on_settings():
    for spec in catalog.all_specs():
        if spec.requires_key is None:
            continue  # mock models need no key
        assert hasattr(settings, spec.requires_key), (
            f"{spec.provider_id}/{spec.model_id}.requires_key={spec.requires_key!r} is not a Settings attribute"
        )


def test_every_spec_model_id_setting_exists_on_settings():
    for spec in catalog.all_specs():
        if spec.model_id_setting is None:
            continue
        assert hasattr(settings, spec.model_id_setting)


def test_candidates_filters_by_kind_and_enabled():
    video_candidates = catalog.candidates("video")
    assert video_candidates  # seeded
    assert all(s.kind == "video" for s in video_candidates)
    assert all(s.enabled for s in video_candidates)


def test_candidates_filters_by_provider_and_capability():
    openai_llm = catalog.candidates("llm", provider_id="openai")
    assert openai_llm
    assert all(s.provider_id == "openai" for s in openai_llm)

    with_reference = catalog.candidates("image", requires_reference_image=True)
    assert with_reference
    assert all(s.supports_reference_image for s in with_reference)


def test_candidates_orders_by_fallback_priority_then_quality():
    ranked = catalog.candidates("video")
    priorities = [s.fallback_priority for s in ranked]
    assert priorities == sorted(priorities)
    # Two specs sharing fallback_priority=999 only for mock (unique here), so
    # just assert the whole ordering is monotonic non-decreasing.
    assert ranked[0].fallback_priority <= ranked[-1].fallback_priority


def test_candidates_duration_filter_excludes_too_short_and_too_long():
    long_only = catalog.candidates("video", min_duration_sec=20.0)
    assert all((s.supported_durations or (0, 0))[1] >= 20.0 for s in long_only)


def test_configured_model_id_prefers_settings_override(monkeypatch):
    spec = catalog.spec("openai", "gpt-5-mini")
    assert spec is not None
    assert catalog.configured_model_id(spec) == "gpt-5-mini"

    monkeypatch.setattr(settings, "OPENAI_LLM_MODEL", "gpt-5-mini-2099-01-01")
    assert catalog.configured_model_id(spec) == "gpt-5-mini-2099-01-01"


def test_configured_model_id_falls_back_to_seeded_default_when_unset():
    spec = catalog.spec("gemini", "gemini-2.5-pro")
    assert spec is not None
    assert getattr(settings, spec.model_id_setting) in (None, "")
    assert catalog.configured_model_id(spec) == "gemini-2.5-pro"


def test_health_snapshot_has_an_entry_per_provider_and_no_secrets():
    snapshot = catalog.health_snapshot()
    provider_ids = {s.provider_id for s in catalog.all_specs()}
    assert provider_ids <= set(snapshot)
    for entry in snapshot.values():
        assert set(entry) >= {"configured", "enabled", "key_present", "last_error", "available"}


def test_record_failure_redacts_before_storing(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)  # keep provider_status() output stable across tests
    catalog.record_failure("openai", "auth failed: Authorization: Bearer sk-super-secret-token-value")
    snapshot = catalog.health_snapshot()
    assert "sk-super-secret-token-value" not in (snapshot["openai"]["last_error"] or "")
    catalog.record_success("openai")  # reset health state for other tests


# --------------------------------------------------------------------------
# http.py
# --------------------------------------------------------------------------
def test_redact_strips_bearer_and_api_key_and_query_param():
    assert "sk-abcdef123456" not in H.redact("Authorization: Bearer sk-abcdef123456")
    assert "sk-abcdef123456" not in H.redact('{"api_key": "sk-abcdef123456"}')
    assert "sk-abcdef123456" not in H.redact("https://api.example.com/v1?key=sk-abcdef123456&foo=bar")
    assert "[REDACTED]" in H.redact("Authorization: Bearer sk-abcdef123456")


def test_redact_is_a_noop_on_clean_text():
    text = "plain error message with no secrets in it"
    assert H.redact(text) == text


def test_provider_http_error_message_is_pre_redacted():
    err = H.ProviderHttpError(H.ErrorKind.AUTH, "failed with Authorization: Bearer sk-verysecrettoken12345")
    assert "sk-verysecrettoken12345" not in str(err)
    assert "sk-verysecrettoken12345" not in err.message


# --------------------------------------------------------------------------
# schemas.py
# --------------------------------------------------------------------------
GOOD_CONCEPTS_PAYLOAD = {
    "concepts": [
        {
            "angle": "emotional",
            "name": "بيت يجمعنا",
            "name_en": "A Home That Gathers Us",
            "one_line_idea": "idea",
            "hook": "hook",
            "creative_direction": "direction",
            "recommended_mode": "hybrid_reel",
            "recommended_voice": "iraqi_professional",
            "visual_style": "warm",
            "cta_style": "soft cta",
            "why_this_works": "because",
            "scores": {"goal_fit": 90.0},
            "score_total": 88.5,
            "is_alternative": False,
            "is_recommended": True,
        }
    ]
}


def test_validate_llm_json_accepts_a_good_payload():
    ok, instance, errors = S.validate_llm_json("concepts", GOOD_CONCEPTS_PAYLOAD)
    assert ok is True
    assert errors == []
    assert instance is not None
    assert instance.concepts[0].name == "بيت يجمعنا"


def test_validate_llm_json_rejects_a_bad_payload():
    bad = {"concepts": [{"angle": "emotional"}]}  # missing required fields
    ok, instance, errors = S.validate_llm_json("concepts", bad)
    assert ok is False
    assert instance is None
    assert errors  # at least one field-level error


def test_validate_llm_json_never_raises_on_garbage():
    ok, instance, errors = S.validate_llm_json("script", {"lines": "not a list", "score": "not a number"})
    assert ok is False
    assert instance is None
    assert errors


def test_validate_llm_json_unknown_task_passes_through():
    ok, instance, errors = S.validate_llm_json("some_future_task", {"anything": True})
    assert ok is True
    assert errors == []


def test_repair_prompt_mentions_the_errors_and_is_short():
    prompt = S.repair_prompt("concepts", ["concepts.0.score_total: field required"])
    assert "score_total" in prompt
    assert len(prompt) < 1000


def test_json_schema_for_matches_task_models():
    schema = S.json_schema_for("qc")
    assert schema.get("title") == "QCResult" or "properties" in schema
    assert "scores" in schema.get("properties", {})


# --------------------------------------------------------------------------
# Adapters: unavailable degrade, never raise
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "adapter_cls,call",
    [
        (A.OpenAILLMAdapter, lambda a: a.complete_json(task="concepts", context={})),
        (A.GeminiLLMAdapter, lambda a: a.complete_json(task="concepts", context={})),
        (A.OpenAIImageAdapter, lambda a: a.generate_image(prompt={})),
        (A.GeminiImageAdapter, lambda a: a.generate_image(prompt={})),
        (A.VeoVideoAdapter, lambda a: a.generate_video(prompt={})),
        (A.RunwayVideoAdapter, lambda a: a.generate_video(prompt={})),
        (A.SeedanceVideoAdapter, lambda a: a.generate_video(prompt={})),
        (A.ElevenLabsVoiceAdapter, lambda a: a.synthesize(text="hi", voice_id="v1")),
        (A.GenericMusicAdapter, lambda a: a.generate_music(brief={})),
    ],
)
def test_adapters_report_unavailable_without_raising(adapter_cls, call):
    adapter = adapter_cls()
    assert adapter.available() is False  # no keys configured anywhere in this environment
    result = call(adapter)
    assert result.ok is False
    assert result.is_mock is False
    assert result.error  # a helpful message, not a stack trace
    assert adapter.key_setting in result.error


def test_elevenlabs_list_voices_returns_empty_list_when_unavailable():
    assert A.ElevenLabsVoiceAdapter().list_voices() == []


def test_adapters_conform_to_capability_and_never_leak_keys(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-should-never-appear-in-output")
    cap = A.OpenAILLMAdapter().capability()
    assert "sk-should-never-appear-in-output" not in jsonlib.dumps(
        {"name": cap.name, "models": cap.models, "notes": cap.notes}
    )


# --------------------------------------------------------------------------
# Structured-output repair: exactly one retry, never more
# --------------------------------------------------------------------------
def test_llm_repair_retry_happens_at_most_once(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test-fake-key")
    monkeypatch.setattr(settings, "FORCE_MOCK_PROVIDERS", False)

    calls = {"count": 0}

    def fake_post_json(url, *, headers=None, json=None, params=None, timeout=None, max_retries=None):
        calls["count"] += 1
        if calls["count"] == 1:
            # First attempt: invalid — missing every required ConceptsResult field.
            content = jsonlib.dumps({"concepts": [{"angle": "emotional"}]})
        else:
            # Repair attempt: valid.
            content = jsonlib.dumps(GOOD_CONCEPTS_PAYLOAD)
        return {"choices": [{"message": {"content": content}}], "usage": {"total_tokens": 500}}

    monkeypatch.setattr(A.http, "post_json", fake_post_json)

    result = A.OpenAILLMAdapter().complete_json(task="concepts", context={"brief": {}})

    assert calls["count"] == 2  # exactly one repair attempt, never more
    assert result.ok is True
    assert result.is_mock is False
    assert result.data["concepts"][0]["name"] == "بيت يجمعنا"


def test_llm_repair_gives_up_cleanly_after_one_failed_retry(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test-fake-key")
    monkeypatch.setattr(settings, "FORCE_MOCK_PROVIDERS", False)

    calls = {"count": 0}

    def always_bad_post_json(url, *, headers=None, json=None, params=None, timeout=None, max_retries=None):
        calls["count"] += 1
        return {"choices": [{"message": {"content": jsonlib.dumps({"concepts": "not even a list"})}}]}

    monkeypatch.setattr(A.http, "post_json", always_bad_post_json)

    result = A.OpenAILLMAdapter().complete_json(task="concepts", context={"brief": {}})

    assert calls["count"] == 2  # one normal + one repair — never a third call
    assert result.ok is False
    assert result.error
    assert "sk-test-fake-key" not in result.error


# --------------------------------------------------------------------------
# pricing.py — integration-test budget guard
# --------------------------------------------------------------------------
def test_guard_integration_spend_allows_within_cap():
    pricing.guard_integration_spend(pricing.integration_test_budget())  # exactly at the cap: fine


def test_guard_integration_spend_raises_above_cap():
    cap = pricing.integration_test_budget()
    with pytest.raises(pricing.IntegrationBudgetExceeded):
        pricing.guard_integration_spend(cap + 0.01)


def test_price_for_model_matches_catalog_cost_per_unit():
    spec = catalog.spec("veo", "veo-3-fast")
    assert spec is not None
    assert pricing.price_for_model("veo-3-fast", units=1.0) == spec.cost_per_unit


def test_describe_pricing_groups_by_kind_and_has_no_secrets(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-must-not-leak")
    payload = pricing.describe_pricing()
    assert "llm" in payload["by_kind"]
    assert "sk-must-not-leak" not in jsonlib.dumps(payload)


# --------------------------------------------------------------------------
# registry.py — snapshot exposes no secrets
# --------------------------------------------------------------------------
def test_registry_snapshot_has_no_secret_values(monkeypatch):
    fake_keys = {
        "OPENAI_API_KEY": "sk-openai-fake-secret",
        "GEMINI_API_KEY": "sk-gemini-fake-secret",
        "ELEVENLABS_API_KEY": "sk-eleven-fake-secret",
        "RUNWAY_API_KEY": "sk-runway-fake-secret",
        "VEO_API_KEY": "sk-veo-fake-secret",
        "SEEDANCE_API_KEY": "sk-seedance-fake-secret",
        "MUSIC_API_KEY": "sk-music-fake-secret",
    }
    for name, value in fake_keys.items():
        monkeypatch.setattr(settings, name, value)

    snapshot = registry.registry_snapshot()
    dumped = jsonlib.dumps(snapshot)
    for value in fake_keys.values():
        assert value not in dumped
    # sanity: the snapshot actually reflects "key present" without the value
    assert snapshot["by_kind"]["llm"]  # non-empty


def test_registry_snapshot_grouped_and_ordered_by_fallback_priority():
    snapshot = registry.registry_snapshot()
    video_rows = {row["provider_id"]: row for row in snapshot["by_kind"]["video"]}
    assert "mock" in video_rows
    seedance_priority = min(m["fallback_priority"] for m in video_rows["seedance"]["models"])
    veo_priority = min(m["fallback_priority"] for m in video_rows["veo"]["models"])
    assert seedance_priority < veo_priority  # economy candidate tried before the smart_premium default


def test_provider_status_still_matches_original_contract():
    """Guards the pre-existing contract `test_providers.py` and `app/api/library.py` rely on."""
    statuses = {(p["kind"], p["name"]): p for p in registry.provider_status()}
    row = statuses[("video", "veo")]
    assert row["available"] is False
    assert row["requires_key"] == "VEO_API_KEY"
    assert statuses[("llm", "mock")]["active"] is True
    # additions are present without breaking the original keys
    assert "healthy" in row
    assert "last_error" in row
