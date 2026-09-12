"""Hook variants — the first three seconds, tested rather than guessed.

On a paid campaign the opening line decides almost everything. A viewer gives a
vertical ad about three seconds before the thumb moves, so two ads sharing a
body and differing only in their hook routinely differ by several multiples in
cost per result. Which hook wins is not knowable in advance — it is measured,
which means you need more than one to measure.

So this module turns one approved script into a small set of genuinely
different openings, each a complete creative that can carry its own ad-set.
Two constraints shape it:

* **Deterministic and free.** Variants are built by restating the script's own
  offer through Iraqi hook patterns, not by another paid model call. A
  hook-testing feature that costs a model call per variant per project is a
  feature nobody runs.
* **Different in kind, not in wording.** Five rephrasings of one idea test
  nothing. The patterns below attack from genuinely different angles —
  question, number, objection, urgency, outcome — because that is the axis
  that actually moves performance.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from app.services.script_qa import IRAQI_MARKERS, WEAK_HOOK_OPENERS, review_script

#: How many seconds of the ad a hook owns. Past this the viewer has decided.
HOOK_WINDOW_SEC = 3.0

#: A hook longer than this cannot be spoken inside the window.
MAX_HOOK_WORDS = 11


@dataclass
class HookVariant:
    """One testable opening."""

    key: str
    angle: str
    angle_ar: str
    voice_line: str
    on_screen_text: str
    score: float = 0.0
    rationale_ar: str = ""
    rationale_en: str = ""
    warnings: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "angle": self.angle,
            "angle_ar": self.angle_ar,
            "voice_line": self.voice_line,
            "on_screen_text": self.on_screen_text,
            "score": round(self.score, 1),
            "rationale_ar": self.rationale_ar,
            "rationale_en": self.rationale_en,
            "warnings": list(self.warnings),
        }


# --------------------------------------------------------------------------
# Facts pulled out of the approved script
# --------------------------------------------------------------------------
_NUMBER = re.compile(r"[\d٠-٩]+(?:[.,][\d٠-٩]+)?\s*(?:٪|%|متر|م٢|سنة|سنوات|شهر|أشهر|ألف|مليون)?")

#: Offer words worth leading with, in the order a buyer cares about them.
_OFFER_HINTS = ("دفعة", "قسط", "أقساط", "تسليم", "سعر", "خصم", "مساحة", "متر", "٪", "%")


def _first_sentence(text: str) -> str:
    parts = re.split(r"[.!؟\n]", text or "")
    return next((p.strip() for p in parts if p.strip()), "")


def extract_facts(script: Dict[str, Any]) -> Dict[str, Any]:
    """The concrete things a hook can be built from.

    A hook without a specific — a number, a place, a term — is a mood, and a
    mood does not stop a thumb.
    """
    body = " ".join(
        str(script.get(key) or "") for key in ("hook", "body", "cta", "voice_over_text")
    )
    numbers = [m.group(0).strip() for m in _NUMBER.finditer(body) if m.group(0).strip()]
    offer = next(
        (frag.strip() for frag in re.split(r"[،.!؟\n]", body)
         if any(hint in frag for hint in _OFFER_HINTS)),
        "",
    )
    return {
        "numbers": numbers[:4],
        "offer": offer[:90],
        "first_line": _first_sentence(script.get("voice_over_text") or script.get("body") or ""),
    }


# --------------------------------------------------------------------------
# Patterns
# --------------------------------------------------------------------------
def _prefixed(preposition: str, name: str) -> str:
    """Attach a one-letter preposition the way Arabic actually writes it.

    "ب" joins directly to an Arabic word ("بمدينة الورد"); the tatweel form
    "بـ" is for a Latin or foreign name that cannot be joined ("بـTADAFQ").
    """
    first = (name or "").lstrip()[:1]
    joins = bool(first) and "؀" <= first <= "ۿ"
    return f"{preposition}{name}" if joins else f"{preposition}ـ{name}"


def _question(facts: Dict[str, Any], project_name: str) -> Optional[str]:
    if not facts["offer"]:
        return None
    return "تدور على بيت بسعر يناسبك؟"


def _number(facts: Dict[str, Any], project_name: str) -> Optional[str]:
    """Lead with the offer the script already makes — never a new claim.

    Inventing a figure here would be a false statement in a property ad, so
    this restates the offer fragment verbatim and adds nothing to it.
    """
    offer = facts.get("offer") or ""
    if not offer or not facts["numbers"]:
        return None
    return f"{offer.strip().rstrip('،.')} — {_prefixed('ب', project_name)}."


def _objection(facts: Dict[str, Any], project_name: str) -> Optional[str]:
    return "تكول ما أكدر أشتري هسه؟ اسمعني دقيقة."


def _urgency(facts: Dict[str, Any], project_name: str) -> Optional[str]:
    if not facts["offer"]:
        return None
    return f"هاي الفرصة {_prefixed('ب', project_name)} ما راح تدوم هواي."


def _outcome(facts: Dict[str, Any], project_name: str) -> Optional[str]:
    return f"تخيل نفسك بمفتاح بيتك {_prefixed('ب', project_name)}."


#: (key, angle_en, angle_ar, builder, why it works)
PATTERNS: Sequence[tuple] = (
    ("question", "question", "سؤال مباشر", _question,
     "A question makes the viewer answer in their head, which is engagement before a single claim.",
     "السؤال يخلي المشاهد يجاوب بنفسه — يعني تفاعل قبل ما تدّعي أي شي."),
    ("number", "specific_number", "رقم محدد", _number,
     "A concrete number is the fastest proof that this is a real offer and not an image ad.",
     "الرقم المحدد أسرع دليل إن العرض حقيقي مو مجرد إعلان صورة."),
    ("objection", "objection", "كسر اعتراض", _objection,
     "Naming the objection first disarms it; the viewer expects a pitch and gets understanding.",
     "تذكر الاعتراض أول شي فتنزع سلاحه — المشاهد ينتظر دعاية ويلگه فهم."),
    ("urgency", "urgency", "إلحاح", _urgency,
     "Scarcity works, but only when it is true — never attach it to a permanent offer.",
     "الندرة تشتغل بس إذا صادقة — لا تستعملها ويّا عرض دائم."),
    ("outcome", "outcome", "النتيجة", _outcome,
     "Selling the moment of ownership rather than the property is what luxury advertising does.",
     "تبيع لحظة التملك مو العقار — هذا أسلوب الإعلان الفخم."),
)


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------
def _score_hook(line: str, script: Dict[str, Any]) -> tuple[float, List[str]]:
    """Score a candidate with the same QA the real script is judged by."""
    candidate = {**script, "hook": line}
    lines = list(candidate.get("lines") or [])
    if lines:
        lines = [{**lines[0], "voice_line": line}] + lines[1:]
        candidate["lines"] = lines
    review = review_script(candidate)
    warnings = [issue.message_ar for issue in review.issues if issue.line_index == 0]
    return float(review.dimensions.get("hook_strength", 0.0)), warnings


def generate_variants(
    script: Dict[str, Any], *, project_name: str = "", limit: int = 4
) -> List[HookVariant]:
    """Build testable openings for one approved script.

    The script's own hook is always included as the control — a test without a
    control tells you which new thing won, not whether any of them beat what
    you already had.
    """
    facts = extract_facts(script)
    name = (project_name or "").strip() or "المشروع"

    control_line = (script.get("hook") or facts["first_line"] or "").strip()
    variants: List[HookVariant] = []
    seen = set()

    if control_line:
        score, warnings = _score_hook(control_line, script)
        variants.append(HookVariant(
            key="control", angle="control", angle_ar="الأصلي",
            voice_line=control_line, on_screen_text=_on_screen(control_line),
            score=score,
            rationale_en="The approved hook, kept as the control to measure the others against.",
            rationale_ar="الخطّاف المعتمد — يبقى كمرجع نقيس عليه البقية.",
            warnings=warnings,
        ))
        seen.add(_normalise(control_line))

    for key, angle, angle_ar, builder, why_en, why_ar in PATTERNS:
        line = builder(facts, name)
        if not line:
            continue
        line = _trim_to_window(line)
        if _normalise(line) in seen:
            continue
        score, warnings = _score_hook(line, script)
        seen.add(_normalise(line))
        variants.append(HookVariant(
            key=key, angle=angle, angle_ar=angle_ar,
            voice_line=line, on_screen_text=_on_screen(line),
            score=score, rationale_en=why_en, rationale_ar=why_ar, warnings=warnings,
        ))

    # Control first, then strongest. A tester scans the top of the list.
    control = [v for v in variants if v.key == "control"]
    rest = sorted((v for v in variants if v.key != "control"), key=lambda v: -v.score)
    return (control + rest)[: max(limit, 1)]


def _normalise(line: str) -> str:
    return re.sub(r"\s+", " ", (line or "").strip()).rstrip("؟?!.")


def _trim_to_window(line: str) -> str:
    """A hook that cannot be said in three seconds is not a hook."""
    words = line.split()
    if len(words) <= MAX_HOOK_WORDS:
        return line
    return " ".join(words[:MAX_HOOK_WORDS]).rstrip("،") + "."


def _on_screen(line: str) -> str:
    """The screen says less than the voice — reading competes with listening."""
    stripped = re.sub(r"\s+", " ", (line or "").strip())
    words = stripped.split()
    if len(words) <= 6:
        return stripped
    # Cut at the question mark when there is one: half a question on screen
    # reads as a typo.
    for cut in range(min(6, len(words)), 0, -1):
        if words[cut - 1].endswith(("؟", "!")):
            return " ".join(words[:cut])
    return " ".join(words[:6]).rstrip("،") + "…"


def variant_slug(variant: HookVariant) -> str:
    """Filename-safe label so an ad manager can tell creatives apart."""
    return f"hook-{variant.key}"


def weak_openers() -> Sequence[str]:
    """Exposed so the UI can explain why a hook scored badly."""
    return WEAK_HOOK_OPENERS


def iraqi_markers() -> Sequence[str]:
    return IRAQI_MARKERS


# --------------------------------------------------------------------------
# Applying a chosen hook
# --------------------------------------------------------------------------
def apply_to_script_lines(
    lines: Sequence[Dict[str, Any]], variant: HookVariant
) -> List[Dict[str, Any]]:
    """Swap the opening line for a chosen variant, leaving everything else.

    The body and CTA are the parts the customer approved and the parts the
    dialect QA already passed; a hook test changes the first three seconds and
    nothing else, or it is not a hook test.
    """
    updated = [dict(line) for line in lines]
    if not updated:
        return updated
    index = next(
        (i for i, line in enumerate(updated) if line.get("role") == "hook"), 0
    )
    updated[index]["voice_line"] = variant.voice_line
    updated[index]["on_screen_text"] = variant.on_screen_text
    return updated
