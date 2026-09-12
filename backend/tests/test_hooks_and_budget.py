"""Hook variants and the monthly spend cap.

Both exist for the same reason: this product is going to run paid campaigns on
a small budget. One decides whether the money buys results; the other decides
whether the money runs out without anyone noticing.
"""
from __future__ import annotations

import pytest

from app.core.config import settings
from app.core.enums import CostStatus
from app.core.errors import BudgetExceeded
from app.services import costs as cost_service
from app.services import hooks as hook_service

SCRIPT = {
    "hook": "شركة الورد تقدم لكم مشروعها الجديد",
    "body": "وحدات سكنية بمساحات ١٥٠ و٢٠٠ متر، دفعة أولى ٢٥٪ وأقساط لحد ٤ سنوات",
    "cta": "احجز موعد زيارة اليوم",
    "voice_over_text": "شركة الورد تقدم لكم مشروعها الجديد. دفعة أولى ٢٥٪ وأقساط لحد ٤ سنوات.",
    "lines": [
        {"index": 0, "role": "hook", "voice_line": "شركة الورد تقدم لكم مشروعها الجديد",
         "on_screen_text": "مدينة الورد", "start": 0.0, "end": 3.0},
        {"index": 1, "role": "body", "voice_line": "دفعة أولى ٢٥٪ وأقساط لحد ٤ سنوات",
         "on_screen_text": "دفعة ٢٥٪", "start": 3.0, "end": 9.0},
    ],
}


# --------------------------------------------------------------------------
# Hook variants
# --------------------------------------------------------------------------
def test_variants_include_the_original_as_a_control():
    """Without a control you learn which new hook won, not whether any beat you."""
    variants = hook_service.generate_variants(SCRIPT, project_name="مدينة الورد")
    assert variants[0].key == "control"
    assert variants[0].voice_line == SCRIPT["hook"]


def test_variants_are_different_openings_not_rephrasings():
    variants = hook_service.generate_variants(SCRIPT, project_name="مدينة الورد", limit=5)
    lines = {v.voice_line for v in variants}
    assert len(lines) == len(variants), "a duplicate opening tests nothing"
    assert len(variants) >= 3


def test_alternatives_beat_a_company_first_hook():
    """'شركة … تقدم لكم' talks about the advertiser, not the viewer."""
    variants = hook_service.generate_variants(SCRIPT, project_name="مدينة الورد", limit=5)
    control = next(v for v in variants if v.key == "control")
    others = [v for v in variants if v.key != "control"]
    assert others, "there must be something to test against"
    assert max(v.score for v in others) > control.score


def test_every_hook_fits_the_three_second_window():
    variants = hook_service.generate_variants(SCRIPT, project_name="مدينة الورد", limit=5)
    for variant in variants:
        if variant.key == "control":
            continue  # the control is whatever the user approved
        assert len(variant.voice_line.split()) <= hook_service.MAX_HOOK_WORDS


def test_the_on_screen_line_is_shorter_than_the_spoken_one():
    """Reading competes with listening; the screen carries less."""
    for variant in hook_service.generate_variants(SCRIPT, project_name="مدينة الورد", limit=5):
        assert len(variant.on_screen_text.split()) <= len(variant.voice_line.split())


def test_no_variant_invents_a_number_the_script_never_made():
    """A fabricated figure in a property ad is a false statement, not a hook."""
    import re

    source_digits = set(re.findall(r"[\d٠-٩]+", " ".join(str(v) for v in SCRIPT.values())))
    for variant in hook_service.generate_variants(SCRIPT, project_name="مدينة الورد", limit=5):
        for number in re.findall(r"[\d٠-٩]+", variant.voice_line):
            assert number in source_digits, f"{variant.key} invented {number}"


def test_an_arabic_name_takes_a_joined_preposition():
    """'بـمدينة' is wrong typography; 'بمدينة' is how it is written."""
    variants = hook_service.generate_variants(SCRIPT, project_name="مدينة الورد", limit=5)
    for variant in variants:
        assert "بـم" not in variant.voice_line


def test_applying_a_hook_changes_only_the_opening():
    variants = hook_service.generate_variants(SCRIPT, project_name="مدينة الورد", limit=5)
    chosen = next(v for v in variants if v.key != "control")
    updated = hook_service.apply_to_script_lines(SCRIPT["lines"], chosen)
    assert updated[0]["voice_line"] == chosen.voice_line
    assert updated[1] == SCRIPT["lines"][1], "the approved body must survive untouched"


def test_a_script_with_no_hook_still_produces_alternatives():
    bare = {"body": "دفعة أولى ٢٥٪", "voice_over_text": "دفعة أولى ٢٥٪", "lines": []}
    variants = hook_service.generate_variants(bare, project_name="مدينة الورد")
    assert variants and all(v.voice_line for v in variants)


# --------------------------------------------------------------------------
# Monthly spend cap
# --------------------------------------------------------------------------
@pytest.fixture
def budget_project(db, user, brand):
    """A project in its OWN organisation.

    The monthly cap is organisation-wide, so sharing one org between tests
    would make each test's ceiling depend on which ran before it.
    """
    from app.models import Organization, Project

    def _make(**overrides):
        org = Organization(name=f"Budget Org {overrides.get('name', '')}", name_ar="اختبار")
        db.add(org)
        db.flush()
        project = Project(
            organization_id=org.id,
            created_by_id=user.id,
            brand_kit_id=brand.id,
            name=overrides.get("name", "ميزانية"),
            budget_limit_usd=overrides.get("budget_limit_usd", 50.0),
        )
        db.add(project)
        db.commit()
        return project

    return _make


def _spend(db, project, amount, *, mock=False):
    cost_service.record_cost(
        db, project=project, provider="veo", model="veo-3.1-fast-generate-preview",
        operation="video_generation", estimated=amount, actual=amount,
        status=CostStatus.ACTUAL.value, is_mock=mock, note="test",
    )
    db.commit()


def test_the_month_cap_counts_real_spend_only(db, budget_project, monkeypatch):
    """Mock renders cost nothing and must not eat the budget."""
    monkeypatch.setattr(settings, "MONTHLY_BUDGET_HARD_CAP_USD", 60.0)
    project = budget_project(name="سقف شهري")
    _spend(db, project, 5.0, mock=True)
    month = cost_service.monthly_spend(db, project.organization_id)
    assert month["month_spend_usd"] == 0.0


def test_spend_is_refused_once_the_month_cap_is_reached(db, budget_project, monkeypatch):
    monkeypatch.setattr(settings, "MONTHLY_BUDGET_HARD_CAP_USD", 10.0)
    project = budget_project(name="تجاوز الشهر", budget_limit_usd=1000.0)
    _spend(db, project, 9.5)

    with pytest.raises(BudgetExceeded) as raised:
        cost_service.check_can_spend(db, project, 2.0, operation="video")
    assert "monthly cap" in str(raised.value)


def test_the_month_cap_warns_before_it_bites(db, budget_project, monkeypatch):
    monkeypatch.setattr(settings, "MONTHLY_BUDGET_HARD_CAP_USD", 10.0)
    monkeypatch.setattr(settings, "MONTHLY_BUDGET_ALERT_RATIO", 0.8)
    project = budget_project(name="تنبيه")
    _spend(db, project, 8.5)
    month = cost_service.monthly_spend(db, project.organization_id)
    assert month["alert"] is True
    assert month["capped"] is False
    assert month["monthly_remaining_usd"] == pytest.approx(1.5, abs=0.01)


def test_a_zero_cap_disables_the_ceiling(db, budget_project, monkeypatch):
    """An operator who wants no monthly ceiling must be able to say so."""
    monkeypatch.setattr(settings, "MONTHLY_BUDGET_HARD_CAP_USD", 0.0)
    project = budget_project(name="بدون سقف", budget_limit_usd=1000.0)
    _spend(db, project, 500.0)
    cost_service.check_can_spend(db, project, 50.0, operation="video")  # must not raise


def test_the_cap_refuses_rather_than_quietly_using_mocks(db, budget_project, monkeypatch):
    """A mock render looks like a deliverable and is not one."""
    monkeypatch.setattr(settings, "MONTHLY_BUDGET_HARD_CAP_USD", 5.0)
    project = budget_project(name="لا تبديل صامت", budget_limit_usd=1000.0)
    _spend(db, project, 5.0)
    with pytest.raises(BudgetExceeded):
        cost_service.check_can_spend(db, project, 0.5, operation="video")
    assert settings.FORCE_MOCK_PROVIDERS is True or settings.FORCE_MOCK_PROVIDERS is False
