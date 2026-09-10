"""Provider abstraction, model router, prompt compiler, retries."""
from __future__ import annotations

from app.core.enums import ProductionMethod, QualityLevel
from app.providers import model_router
from app.providers.base import ImageProvider, LLMProvider, MusicProvider, VideoProvider, VoiceProvider
from app.providers.prompt_compiler import compile_scene_prompt, serialize_for_provider
from app.providers.quality_judge import judge_scene, plan_retry
from app.providers.registry import get_image, get_llm, get_music, get_video, get_voice, provider_status


def test_registry_falls_back_to_mock_without_keys():
    assert get_llm().is_mock
    assert get_image().is_mock
    assert get_video().is_mock
    assert get_voice().is_mock
    assert get_music().is_mock


def test_adapters_conform_to_interfaces():
    assert isinstance(get_llm(), LLMProvider)
    assert isinstance(get_image(), ImageProvider)
    assert isinstance(get_video(), VideoProvider)
    assert isinstance(get_voice(), VoiceProvider)
    assert isinstance(get_music(), MusicProvider)


def test_unconfigured_real_adapter_reports_unavailable():
    statuses = {(p["kind"], p["name"]): p for p in provider_status()}
    assert statuses[("video", "veo")]["available"] is False
    assert statuses[("video", "veo")]["requires_key"] == "VEO_API_KEY"
    assert statuses[("llm", "mock")]["active"] is True


def test_mock_llm_returns_structured_iraqi_content():
    result = get_llm().complete_json(
        task="concepts",
        context={"brief": {"name": "مدينة الورد", "goal": "leads", "cta": "اتصل بينا"}},
    )
    assert result.ok and result.is_mock and result.cost_usd == 0.0
    concepts = result.data["concepts"]
    assert len([c for c in concepts if not c["is_alternative"]]) == 3
    assert all(c["hook"] for c in concepts)
    assert any(c["is_recommended"] for c in concepts)


def test_scene_source_priority_prefers_owned_media():
    method, _ = model_router.choose_method(
        has_original_video=True, has_original_photo=True, is_hero=True, is_hook=True
    )
    assert method == ProductionMethod.ORIGINAL_VIDEO.value

    method, _ = model_router.choose_method(
        has_original_video=False, has_original_photo=True, is_hero=False, is_hook=False
    )
    assert method == ProductionMethod.ORIGINAL_PHOTO.value

    method, _ = model_router.choose_method(
        has_original_video=False, has_original_photo=False, is_hero=False, is_hook=False,
        fidelity_locked=False,
    )
    assert method == ProductionMethod.AI_IMAGE.value


def test_router_downgrades_when_budget_is_short():
    decision = model_router.route(
        scene={"production_method": ProductionMethod.AI_VIDEO.value, "start_time": 0, "end_time": 5, "is_hero": True},
        quality_level=QualityLevel.SMART_PREMIUM.value,
        remaining_budget_usd=0.10,
    )
    assert decision.downgraded is True
    assert decision.method == ProductionMethod.AI_IMAGE.value
    assert decision.estimated_cost_usd <= 0.10 or decision.method != ProductionMethod.AI_VIDEO.value


def test_local_methods_cost_nothing_from_providers():
    decision = model_router.route(
        scene={"production_method": ProductionMethod.ORIGINAL_VIDEO.value, "start_time": 0, "end_time": 4},
    )
    assert decision.provider == "local"
    assert decision.estimated_cost_usd == 0.0


def test_prompt_compiler_never_ships_the_raw_script():
    scene = {
        "scene_number": 2,
        "purpose": "hero",
        "voice_line": "بيت يجمع العائلة بمدينة الورد",
        "on_screen_text": "بيت يجمعكم",
        "camera_movement": "دفع بطيء للأمام",
        "lighting": "ضوء ذهبي",
        "start_time": 3,
        "end_time": 7,
        "production_method": "ai_video",
    }
    prompt = compile_scene_prompt(
        scene=scene,
        project={"name": "مدينة الورد", "category": "real_estate", "architecture_fidelity_lock": True},
        reference_urls=["https://example.com/ref.jpg"],
    )
    assert "voice_line" not in prompt
    assert scene["voice_line"] not in str(prompt.get("subject", ""))
    assert prompt["negative"]
    assert any("reference" in c for c in prompt["constraints"])

    veo = serialize_for_provider(prompt, "veo")
    runway = serialize_for_provider(prompt, "runway")
    assert veo != runway  # per-provider compilation strategies


def test_fidelity_lock_blocks_invented_architecture():
    prompt = compile_scene_prompt(
        scene={"scene_number": 1, "production_method": "ai_video"},
        project={"name": "X", "architecture_fidelity_lock": True},
        reference_urls=[],
    )
    assert any("generic architecture" in c for c in prompt["constraints"])
    assert "invented building details" in prompt["negative"]


def test_retry_ladder_is_finite_and_budget_aware():
    first = plan_retry(attempt=1, max_attempts=3, budget_ok=True)
    assert first.should_retry and first.strategy == "optimize_prompt"

    second = plan_retry(attempt=2, max_attempts=3, budget_ok=True)
    assert second.should_retry and second.switch_provider

    last = plan_retry(attempt=3, max_attempts=3, budget_ok=True)
    assert last.should_retry is False

    broke = plan_retry(attempt=1, max_attempts=3, budget_ok=False)
    assert broke.should_retry is False and broke.strategy == "budget_stop"


def test_quality_judge_scores_all_dimensions():
    verdict = judge_scene(scene={"id": "s1", "production_method": "ai_video"}, result_meta={"quality_hint": 95})
    assert 0 < verdict.score <= 100
    assert len(verdict.breakdown) == 11
    owned = judge_scene(scene={"id": "s2", "production_method": "original_photo"}, result_meta={})
    assert owned.score >= 85  # owned media is inherently accurate
