"""Gulf Arabic is not Iraqi, and the old checks could not see the difference.

`MSA_TO_IRAQI` catches Standard Arabic. A model drifting into Gulf Arabic
slips past it untouched: every word is colloquial, nothing fires, and the
script reads as another country's ad. The user said it plainly — "النص يستخدم
الخليجي أكثر من العراقي" — and no dimension in the score disagreed with him.
"""
from __future__ import annotations

from app.services.dialect import (
    GULF_TO_IRAQI,
    find_non_iraqi,
    iraqi_writing_rules,
    replace_word,
    soften_gulf,
)
from app.services.script_qa import QA_WEIGHTS, review_script

GULF_LINE = "أبغى بيت وايد زين، الحين تكدر تحجز، ويش رايك؟"
IRAQI_LINE = "أريد بيت هواي زين، هسه تكدر تحجز، شنو رايك؟"


def _script(line: str) -> dict:
    return {
        "lines": [{"voice_line": line, "on_screen": ""}],
        "hook": "شوف هالشي",
        "cta": "اتصل بينا",
    }


def test_the_weights_sum_to_one():
    """The guard for the mistake made while adding `gulf_free`.

    It was added to the table instead of taking its share from the dimensions
    it refines, which pushed the maximum score to 110 and quietly diluted
    every other dimension. A weight table is only ever edited in a hurry.
    """
    assert round(sum(QA_WEIGHTS.values()), 6) == 1.0


def test_gulf_words_are_found_with_their_iraqi_replacement():
    flags = {f.found: f.suggest for f in find_non_iraqi(GULF_LINE) if f.kind == "gulf"}
    assert flags["أبغى"] == "أريد"
    assert flags["وايد"] == "هواي"
    assert flags["الحين"] == "هسه"
    assert flags["ويش"] == "شنو"


def test_an_iraqi_line_is_left_alone():
    """False positives cost more trust than misses — nothing here may fire."""
    assert [f.found for f in find_non_iraqi(IRAQI_LINE) if f.kind == "gulf"] == []


def test_matching_is_on_word_boundaries():
    """"وش" must not fire inside "وشلون", and prefixes must not hide a word."""
    assert [f.found for f in find_non_iraqi("وشلون صار الوضع") if f.kind == "gulf"] == []
    assert any(f.found == "وايد" for f in find_non_iraqi("عندنا وايد وحدات"))


def test_the_score_punishes_gulf_harder_than_it_punishes_nothing():
    gulf = review_script(_script(GULF_LINE))
    iraqi = review_script(_script(IRAQI_LINE))
    assert gulf.dimensions["gulf_free"] < 50
    assert iraqi.dimensions["gulf_free"] == 100
    assert gulf.score < iraqi.score - 5, "Gulf wording must cost real points"
    assert any(i.code == "gulf_not_iraqi" for i in gulf.issues)


def test_the_repair_pass_rewrites_gulf_into_iraqi():
    assert soften_gulf(GULF_LINE) == IRAQI_LINE


def test_replacing_one_word_leaves_the_rest_of_the_line_alone():
    once = replace_word(GULF_LINE, "وايد", "هواي")
    assert "هواي" in once
    assert "أبغى" in once, "only the chosen word may change"


def test_the_model_is_told_what_iraqi_is_not():
    """The root cause: the prompt said "Iraqi-Arabic-first" and nothing else.

    A model given that writes the Gulf Arabic it has far more of, and the
    result looks compliant because it is dialect — just not this one.
    """
    rules = iraqi_writing_rules("iraqi_professional")
    assert "مو خليجي" in rules
    assert "هسه" in rules
    for banned in ("أبغى", "وايد", "الحين"):
        assert banned in rules


def test_the_writing_tasks_actually_receive_the_rules():
    from app.providers.adapters import _llm_system_prompt

    assert "مو خليجي" in _llm_system_prompt("script", "iraqi_professional")
    assert "مو خليجي" in _llm_system_prompt("concepts", "iraqi_luxury")
    # A cost estimate does not need dialect rules; noise there is still noise.
    assert "مو خليجي" not in _llm_system_prompt("qc")


def test_each_occurrence_is_flagged_at_its_own_position():
    """The screen replaces by offset, so every offset has to be real.

    One flag per *word* was the first shape of this, and it cannot work: a
    line that says "وايد" twice needs two decisions, and a panel that offers
    one swap silently leaves the second occurrence in the ad.
    """
    line = "أبغى بيت وايد زين، وايد قريب"
    flags = find_non_iraqi(line)
    assert [f.found for f in flags] == ["أبغى", "وايد", "وايد"]
    for flag in flags:
        assert line[flag.start:flag.end] == flag.found
    assert flags[1].start != flags[2].start


def test_a_longer_entry_claims_its_characters_first():
    """"وش فيه" is one flag, not a phrase plus the "وش" inside it."""
    flags = find_non_iraqi("وش فيه هالبيت")
    assert [f.found for f in flags] == ["وش فيه"]


def test_replacing_by_offset_matches_replacing_by_word():
    """The frontend cuts the line at `start`/`end`; this is that arithmetic.

    If the two ever disagree the panel edits the wrong characters, which looks
    like a broken dictionary rather than a broken index.
    """
    flag = next(f for f in find_non_iraqi(GULF_LINE) if f.found == "وايد")
    by_offset = GULF_LINE[: flag.start] + flag.suggest + GULF_LINE[flag.end:]
    assert by_offset == replace_word(GULF_LINE, "وايد", "هواي")


def test_the_script_payload_locates_every_flag_in_its_own_line():
    from app.models import ScriptVersion
    from app.services.scripts import dialect_flags

    script = ScriptVersion(
        lines=[
            {"index": 0, "role": "hook", "voice_line": "شوف هالشي"},
            {"index": 1, "role": "body", "voice_line": GULF_LINE},
        ],
        hook="شوف هالشي",
        cta="اتصل بينا",
        dialect_preset="iraqi_professional",
    )
    flags = dialect_flags(script)
    assert flags and all(flag["line_index"] == 1 for flag in flags)
    for flag in flags:
        assert GULF_LINE[flag["start"]:flag["end"]] == flag["found"]


def test_every_gulf_entry_has_a_deliberate_replacement():
    """An empty suggestion means "delete this", never "we forgot"."""
    deletions = {"طال عمرك", "دام عزك", "أبشر", "ابشر", "يا بعد قلبي"}
    for gulf, iraqi in GULF_TO_IRAQI.items():
        if not iraqi:
            assert gulf in deletions, f"{gulf} has no replacement and is not a deletion"


def test_punctuation_does_not_hide_a_word():
    """Arabic punctuation lives in the Arabic block; it is not part of a word.

    A boundary rule written as "the whole Arabic range" treats «،» and «؟» as
    letters, so every flagged word sitting at the end of a clause disappears —
    which is where an ad puts its call to action. This line produced no flags
    at all until the class was narrowed to letters, digits and diacritics.
    """
    found = {f.found for f in find_non_iraqi("بادر بالحجز، لا هنت، وياك خطوة بخطوة")}
    assert found == {"بادر بالحجز", "لا هنت"}
    assert {f.found for f in find_non_iraqi("تريد تحجز؟ ويش رايك؟")} == {"ويش"}
