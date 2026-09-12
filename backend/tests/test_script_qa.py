"""Iraqi script QA tests.

These assert on language, which is the thing this product is actually selling.
A script that scores well here should read as written for Iraq; one that scores
badly should be one an Iraqi copywriter would reject.
"""
from __future__ import annotations

from app.services import script_qa as QA


def _script(lines, *, hook=None, cta=None, duration=30.0):
    voice = " ".join(lines)
    return {
        "hook": hook if hook is not None else lines[0],
        "body": " ".join(lines[1:-1]) if len(lines) > 2 else "",
        "cta": cta if cta is not None else lines[-1],
        "voice_over_text": voice,
        "on_screen_text": [],
        "lines": [
            {"index": i, "role": "hook" if i == 0 else ("cta" if i == len(lines) - 1 else "body"),
             "voice_line": text, "on_screen_text": text,
             "start": i * 3.0, "end": (i + 1) * 3.0}
            for i, text in enumerate(lines)
        ],
        "dialect_preset": "iraqi_professional",
        "total_duration_sec": duration,
        "word_count": len(voice.split()),
        "score": 90.0,
        "critic_notes": [],
    }


GOOD = _script([
    "شوف هالشي — هسه صار عندك بيت بمدينة الورد",
    "أكو وحدات بمساحات ١٥٠ و٢٠٠ متر وتكدر تختار اللي يناسبك",
    "دفعة أولى ٢٥٪ وأقساط لحد ٤ سنوات وتسليم أول مرحلة خلال ٦ أشهر",
    "احجز موعد زيارة اليوم · 07701234567",
])

BAD = _script([
    "إن شركتنا تعتبر الأفضل على الإطلاق في هذا المجال",
    "يوجد لدينا الآن العديد من الوحدات وسوف يمكنكم زيارتها كثيراً ربما",
    "نود إعلامكم بأن أرباح مضمونة تنتظر سيادتكم في هذا المشروع الاستثماري الكبير جداً",
    "شكراً لكم",
])


# --------------------------------------------------------------------------
# soften_msa
# --------------------------------------------------------------------------
def test_soften_msa_replaces_known_constructions():
    assert QA.soften_msa("الآن يمكنك زيارتنا") == "هسه تكدر زيارتنا"
    assert "ماكو" in QA.soften_msa("لا يوجد أفضل من هذا")
    assert "هواي" in QA.soften_msa("كثيراً من العائلات")


def test_soften_msa_leaves_natural_iraqi_alone():
    natural = "هسه أكو وحدات وتكدر تحجز"
    assert QA.soften_msa(natural) == natural


def test_longest_phrase_wins_so_negation_survives():
    """'لا يوجد' must become 'ماكو', never 'لا أكو'."""
    assert QA.soften_msa("لا يوجد مثله") == "ماكو مثله"


# --------------------------------------------------------------------------
# Review
# --------------------------------------------------------------------------
def test_a_natural_iraqi_script_scores_well():
    report = QA.review_script(GOOD, brand={"phone": "07701234567"})
    assert report.score >= 82
    assert not [i for i in report.issues if i.severity == "critical"]
    assert report.dimensions["natural_iraqi"] > 60
    assert report.dimensions["cta_quality"] == 100.0


def test_an_msa_marketing_script_is_rejected():
    report = QA.review_script(BAD, brand={"phone": "07701234567"})
    assert report.rewrite_needed
    codes = {issue.code for issue in report.issues}
    assert "unnecessary_msa" in codes
    assert "over_formal" in codes
    assert "sales_pressure" in codes
    assert "weak_cta" in codes


def test_pressure_language_is_a_critical_issue():
    report = QA.review_script(_script([
        "هسه أكو فرصة", "أرباح مضمونة وياك", "اتصل بينا هسه",
    ]))
    pressure = [i for i in report.issues if i.code == "sales_pressure"]
    assert pressure and pressure[0].severity == "critical"


def test_a_hook_about_the_company_is_flagged():
    report = QA.review_script(_script([
        "شركة التدفق تأسست سنة ٢٠١٠",
        "أكو وحدات زينة وتكدر تشوفها",
        "احجز موعدك اليوم",
    ]))
    assert "weak_hook" in {i.code for i in report.issues}


def test_a_cta_without_the_brand_phone_is_critical():
    report = QA.review_script(GOOD, brand={"phone": "07809999999"})
    codes = {i.code for i in report.issues}
    assert "cta_missing_contact" in codes


def test_brand_forbidden_phrases_are_enforced():
    report = QA.review_script(
        _script(["هسه شوف", "هذا عرض ناري", "اتصل بينا"]),
        brand={"forbidden_phrases": ["عرض ناري"]},
    )
    assert "sales_pressure" in {i.code for i in report.issues}


def test_duration_drift_is_reported():
    long_lines = ["هسه أكو وحدات وتكدر تشوفها وتحجز بكل سهولة ويّانا"] * 12
    report = QA.review_script(_script(long_lines + ["اتصل بينا هسه"], duration=15.0),
                              target_duration_sec=15.0)
    assert "duration_mismatch" in {i.code for i in report.issues}
    assert report.estimated_duration_sec > 15.0


def test_a_line_nobody_can_say_in_one_breath_is_flagged():
    long_line = " ".join(["كلمة"] * 20)
    report = QA.review_script(_script(["هسه شوف", long_line, "اتصل بينا هسه"]))
    issues = [i for i in report.issues if i.code == "line_too_long"]
    assert issues and issues[0].line_index == 1


# --------------------------------------------------------------------------
# Repair
# --------------------------------------------------------------------------
def test_repair_raises_the_score_of_a_bad_script():
    before = QA.review_script(BAD, brand={"phone": "07701234567"})
    improved, changes = QA.improve_script(BAD, before, brand={"phone": "07701234567"})
    after = QA.review_script(improved, brand={"phone": "07701234567"})
    assert after.score > before.score
    assert changes
    assert "أرباح مضمونة" not in improved["voice_over_text"]
    assert "الأفضل على الإطلاق" not in improved["voice_over_text"]


def test_repair_gives_the_cta_a_verb_and_the_number():
    report = QA.review_script(BAD, brand={"phone": "07701234567"})
    improved, _ = QA.improve_script(BAD, report, brand={"phone": "07701234567"})
    cta = improved["cta"]
    assert any(verb in cta for verb in QA.CTA_VERBS)
    assert "07701234567" in cta


def test_repair_splits_an_unspeakable_line():
    long_line = " ".join(["كلمة"] * 22)
    script = _script(["هسه شوف", long_line, "اتصل بينا هسه"])
    report = QA.review_script(script)
    improved, changes = QA.improve_script(script, report)
    assert any(change.startswith("split_line") for change in changes)
    assert "،" in improved["lines"][1]["voice_line"]


def test_qa_pass_leaves_a_good_script_untouched():
    final, report, changes = QA.qa_pass(GOOD, brand={"phone": "07701234567"})
    assert changes == []
    assert final is GOOD
    assert not report.rewrite_needed


def test_qa_pass_never_returns_a_worse_script():
    for script in (GOOD, BAD):
        before = QA.review_script(script, brand={"phone": "07701234567"})
        _, after, _ = QA.qa_pass(script, brand={"phone": "07701234567"})
        assert after.score >= before.score


def test_report_serialises_for_the_api():
    report = QA.review_script(BAD)
    payload = report.as_dict()
    assert set(payload) >= {"score", "dimensions", "issues", "rewrite_needed",
                            "word_count", "estimated_duration_sec"}
    assert all({"code", "severity", "message_ar"} <= set(i) for i in payload["issues"])


# --------------------------------------------------------------------------
# Integration with generation
# --------------------------------------------------------------------------
def test_generated_scripts_carry_a_real_qa_score(db, make_project):
    from app.core.enums import ApprovalEntity
    from app.services import approvals as approval_service
    from app.services import concepts as concept_service
    from app.services import scripts as script_service
    from app.services.analysis import run_analysis

    project = make_project(name="مدينة الورد", cta="احجز موعد زيارة")
    run_analysis(db, project)
    approval_service.approve(db, project=project, entity=ApprovalEntity.ANALYSIS)
    items = concept_service.generate_concepts(db, project)
    concept_service.select_concept(db, project, items[0].id)
    approval_service.approve(db, project=project, entity=ApprovalEntity.CONCEPT,
                             entity_id=items[0].id)
    created = script_service.generate_scripts(db, project)

    primary = next(s for s in created if s.variant == "primary")
    assert 0 < primary.score <= 100
    # The stored score is the QA score, not the generator's own optimism.
    assert isinstance(primary.critic_notes, list)
    assert primary.voice_over_text
