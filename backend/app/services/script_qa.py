"""Second-pass Iraqi script QA.

The first pass writes the ad. This pass reads it back the way an Iraqi
copywriter would and asks the questions that decide whether it sounds native:
is this actually Iraqi or is it MSA with Iraqi words sprinkled on top? does the
hook earn the first three seconds? does the CTA tell the listener what to do
and how to do it? will it fit the duration when spoken?

Everything here is deterministic — no model call, no cost — so it runs on every
generated script, including in mock mode, and the fixes it applies are ones we
can defend rather than hope for.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.services import dialect as D

log = logging.getLogger("adflow.script_qa")

# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------
#: MSA constructions that mark a script as translated rather than written for
#: Iraq, mapped to the natural Iraqi equivalent. Only entries we are confident
#: about are listed — a wrong "correction" is worse than none.
MSA_TO_IRAQI: Dict[str, str] = {
    "الآن": "هسه",
    "الأن": "هسه",
    "كيف": "شلون",
    "أين": "وين",
    "يوجد": "أكو",
    "لا يوجد": "ماكو",
    "هناك": "أكو",
    "ليس هناك": "ماكو",
    "كثيرا": "هواي",
    "كثيراً": "هواي",
    "كثير من": "هواي",
    "جيد جدا": "خوش",
    "جيد جداً": "خوش",
    "جيد": "زين",
    "هكذا": "جِذي",
    "معك": "وياك",
    "معكم": "وياكم",
    "سوف": "راح",
    "يمكنك": "تكدر",
    "يمكنكم": "تكدرون",
    "قم بالاتصال": "اتصل",
    "يرجى التواصل": "تواصل وينا",
    "نحن نقدم لكم": "نوفرلك",
    "إن هذا المشروع": "هذا المشروع",
    "يعتبر": "",
    "يُعد": "",
    "يعد من": "من",
    "بالإضافة إلى ذلك": "وهم",
    "علاوة على ذلك": "وبعد",
    "في الوقت الحالي": "هسه",
    "من الممكن أن": "ممكن",
}

#: Register markers: formal address that no Iraqi ad uses when talking to a
#: buyer. Presence of any is a strong signal the line is over-formal.
OVER_FORMAL_MARKERS: Tuple[str, ...] = (
    "سيادتكم", "حضراتكم", "يشرفنا", "نتشرف", "تفضلوا بقبول", "المحترمين",
    "وفقاً للمعايير", "بموجب", "إن شركتنا", "نود إعلامكم", "عليه فإن",
)

#: Pressure and over-claim language. The product forbids exaggeration because
#: it is what makes a real-estate ad read as a scam.
PRESSURE_MARKERS: Tuple[str, ...] = (
    "أرباح مضمونة", "استثمار مضمون", "الأفضل على الإطلاق", "بلا منازع",
    "فرصة العمر", "لا تفوت الفرصة أبداً", "أرباح خيالية", "مجاناً تماماً",
    "حصرياً وبلا منازع", "أسرع قبل فوات الأوان",
)

#: Vague filler that costs seconds and says nothing.
HEDGE_MARKERS: Tuple[str, ...] = ("ربما", "قد يكون", "تقريباً", "نوعاً ما", "من الممكن")

#: Iraqi markers — their absence in a supposedly Iraqi script is the tell.
IRAQI_MARKERS: Tuple[str, ...] = (
    "هسه", "شلون", "أكو", "ماكو", "هواي", "جِذي", "وين", "خوش", "زين",
    "تكدر", "وياك", "وياكم", "شوف", "خلي", "تره", "هالـ", "هاي", "هذا",
    "بيك", "إلك", "الك", "بينه", "بينا", "دز", "چان", "گلي",
)

#: Real-estate vocabulary an Iraqi buyer expects to hear.
REAL_ESTATE_TERMS: Tuple[str, ...] = (
    "وحدات", "مساحات", "دفعة أولى", "أقساط", "تسليم", "طابو", "قاطع",
    "مجمع", "شقة", "شقق", "فيلا", "دوبلكس", "متر", "غرف", "مدخل", "خدمات",
)

#: A CTA has to contain an action. These are the verbs Iraqi ads actually use.
CTA_VERBS: Tuple[str, ...] = (
    "اتصل", "تواصل", "احجز", "راسلنا", "دز", "زورنا", "تعال", "سجل", "شوف",
)

#: Words that carry the hook. A hook that opens with the company name is dead.
WEAK_HOOK_OPENERS: Tuple[str, ...] = ("شركة", "مجموعة", "نحن", "تأسست", "نقدم لكم")

#: Speaking rate used across the product for duration estimates.
WORDS_PER_SECOND = 2.3


@dataclass
class QAIssue:
    code: str
    severity: str  # critical | warning | info
    message_en: str
    message_ar: str
    suggestion_ar: str = ""
    line_index: Optional[int] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code, "severity": self.severity,
            "message_en": self.message_en, "message_ar": self.message_ar,
            "suggestion_ar": self.suggestion_ar, "line_index": self.line_index,
        }


@dataclass
class ScriptQAReport:
    score: float = 0.0
    dimensions: Dict[str, float] = field(default_factory=dict)
    issues: List[QAIssue] = field(default_factory=list)
    rewrite_needed: bool = False
    word_count: int = 0
    estimated_duration_sec: float = 0.0
    target_duration_sec: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "dimensions": self.dimensions,
            "issues": [issue.as_dict() for issue in self.issues],
            "rewrite_needed": self.rewrite_needed,
            "word_count": self.word_count,
            "estimated_duration_sec": self.estimated_duration_sec,
            "target_duration_sec": self.target_duration_sec,
        }

    def notes_ar(self) -> List[str]:
        """The short, human list the UI shows under the script."""
        return [issue.message_ar for issue in self.issues]


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _contains_any(text: str, markers: Tuple[str, ...]) -> List[str]:
    return [marker for marker in markers if marker in text]


def _script_text(script: Dict[str, Any]) -> str:
    lines = script.get("lines") or []
    if lines:
        return " ".join((line.get("voice_line") or "") for line in lines)
    return " ".join(
        str(script.get(key) or "") for key in ("hook", "body", "cta", "voice_over_text")
    )


def estimate_duration(text: str) -> float:
    words = [w for w in re.split(r"\s+", text.strip()) if w]
    return round(len(words) / WORDS_PER_SECOND, 2)


def soften_msa(text: str) -> str:
    """Replace MSA constructions with their natural Iraqi equivalent.

    Longest phrases first, so "لا يوجد" becomes "ماكو" rather than "لا أكو".
    """
    result = text or ""
    for msa in sorted(MSA_TO_IRAQI, key=len, reverse=True):
        if msa in result:
            result = result.replace(msa, MSA_TO_IRAQI[msa])
    return re.sub(r"\s{2,}", " ", result).strip()


# --------------------------------------------------------------------------
# Review
# --------------------------------------------------------------------------
def review_script(
    script: Dict[str, Any],
    *,
    preset: str = "iraqi_professional",
    brand: Optional[Dict[str, Any]] = None,
    target_duration_sec: Optional[float] = None,
) -> ScriptQAReport:
    """Score a generated script across the dimensions that decide if it ships."""
    brand = brand or {}
    preset_config = D.preset(preset)
    lines: List[Dict[str, Any]] = list(script.get("lines") or [])
    text = _script_text(script)
    words = [w for w in re.split(r"\s+", text.strip()) if w]
    target = float(target_duration_sec or script.get("total_duration_sec") or 30.0)
    estimated = estimate_duration(text)

    issues: List[QAIssue] = []
    dimensions: Dict[str, float] = {}

    # --- natural Iraqi phrasing -----------------------------------------
    iraqi_hits = _contains_any(text, IRAQI_MARKERS)
    density = len(iraqi_hits) / max(len(words) / 12.0, 1.0)
    dimensions["natural_iraqi"] = round(min(100.0, 45.0 + density * 28.0), 1)
    if len(iraqi_hits) < 2:
        issues.append(QAIssue(
            "not_iraqi_enough", "critical",
            "The script reads as standard Arabic, not Iraqi speech.",
            "النص يقرأ فصحى مو لهجة عراقية.",
            "استعمل كلمات عراقية طبيعية مثل: هسه، أكو، تكدر، شوف، خوش.",
        ))

    # --- unnecessary MSA -------------------------------------------------
    msa_hits = [m for m in MSA_TO_IRAQI if m in text]
    dimensions["msa_free"] = round(max(0.0, 100.0 - len(msa_hits) * 14.0), 1)
    if msa_hits:
        issues.append(QAIssue(
            "unnecessary_msa", "warning",
            f"Standard-Arabic wording found: {', '.join(msa_hits[:4])}.",
            f"أكو كلمات فصحى ممكن تنبدل: {'، '.join(msa_hits[:4])}.",
            "نبدلها بمقابلها العراقي حتى تنسمع طبيعية.",
        ))

    # --- over-formality --------------------------------------------------
    formal_hits = _contains_any(text, OVER_FORMAL_MARKERS)
    dimensions["register"] = round(max(0.0, 100.0 - len(formal_hits) * 25.0), 1)
    if formal_hits:
        issues.append(QAIssue(
            "over_formal", "warning",
            f"Over-formal address: {', '.join(formal_hits)}.",
            f"أسلوب رسمي زيادة: {'، '.join(formal_hits)}.",
            "الإعلان يحچي ويّا الزبون مثل صديق، مو مثل كتاب رسمي.",
        ))

    # --- sales pressure / over-claim -------------------------------------
    pressure_hits = _contains_any(text, PRESSURE_MARKERS)
    brand_forbidden = _contains_any(text, tuple(brand.get("forbidden_phrases") or ()))
    preset_forbidden = _contains_any(text, tuple(preset_config.get("forbidden") or ()))
    all_forbidden = pressure_hits + brand_forbidden + preset_forbidden
    dimensions["no_pressure"] = round(max(0.0, 100.0 - len(all_forbidden) * 30.0), 1)
    if all_forbidden:
        issues.append(QAIssue(
            "sales_pressure", "critical",
            f"Exaggerated or high-pressure claims: {', '.join(all_forbidden[:3])}.",
            f"أكو مبالغة أو ضغط بالبيع: {'، '.join(all_forbidden[:3])}.",
            "نشيلها — المبالغة تخلي الإعلان يبين مو صادق.",
        ))

    # --- clarity ---------------------------------------------------------
    hedge_hits = _contains_any(text, HEDGE_MARKERS)
    long_lines = [
        index for index, line in enumerate(lines)
        if len((line.get("voice_line") or "").split()) > 16
    ]
    dimensions["clarity"] = round(
        max(0.0, 100.0 - len(hedge_hits) * 12.0 - len(long_lines) * 10.0), 1
    )
    if hedge_hits:
        issues.append(QAIssue(
            "vague_wording", "warning",
            f"Hedging words weaken the offer: {', '.join(hedge_hits)}.",
            f"كلمات مترددة تضعف العرض: {'، '.join(hedge_hits)}.",
            "الإعلان لازم يكون حاسم: تكدر، راح، أكو.",
        ))
    for index in long_lines:
        issues.append(QAIssue(
            "line_too_long", "warning",
            "A line is too long to say in one breath.",
            "أكو سطر طويل ما ينقرأ بنفَس واحد.",
            "نقصّه لجملتين قصيرات.", line_index=index,
        ))

    # --- hook strength ---------------------------------------------------
    hook = (script.get("hook") or (lines[0].get("voice_line") if lines else "") or "").strip()
    hook_words = len(hook.split())
    weak_opener = any(hook.startswith(opener) for opener in WEAK_HOOK_OPENERS)
    hook_score = 100.0
    if not hook:
        hook_score = 0.0
    else:
        if hook_words > 12:
            hook_score -= 25
        if weak_opener:
            hook_score -= 35
        if not _contains_any(hook, IRAQI_MARKERS):
            hook_score -= 15
    dimensions["hook_strength"] = round(max(0.0, hook_score), 1)
    if weak_opener:
        issues.append(QAIssue(
            "weak_hook", "warning",
            "The hook opens by talking about the company, not the viewer.",
            "الخطّاف يبدي بالحچي عن الشركة مو عن الزبون.",
            "ابدي بفايدة الزبون أو بسؤال يخصه.", line_index=0,
        ))
    elif hook and hook_words > 12:
        issues.append(QAIssue(
            "hook_too_long", "warning",
            "The hook is longer than the first three seconds allow.",
            "الخطّاف أطول من أول ٣ ثواني.",
            "خله أقصر — جملة وحدة تشد النظر.", line_index=0,
        ))

    # --- spoken rhythm ---------------------------------------------------
    line_lengths = [len((line.get("voice_line") or "").split()) for line in lines if line]
    if line_lengths:
        spread = max(line_lengths) - min(line_lengths)
        rhythm = 100.0 - max(0, spread - 8) * 4.0
    else:
        rhythm = 60.0
    dimensions["rhythm"] = round(max(0.0, min(100.0, rhythm)), 1)

    # --- CTA quality -----------------------------------------------------
    cta_text = (script.get("cta") or (lines[-1].get("voice_line") if lines else "") or "").strip()
    has_verb = bool(_contains_any(cta_text, CTA_VERBS))
    on_screen_all = " ".join((line.get("on_screen_text") or "") for line in lines)
    phone = str(brand.get("phone") or "")
    phone_digits = re.sub(r"\D", "", phone)
    contact_shown = bool(phone_digits) and phone_digits in re.sub(
        r"\D", "", D.spell_phone(cta_text) if False else (cta_text + on_screen_all)
    )
    cta_score = (55.0 if has_verb else 0.0) + (45.0 if (contact_shown or not phone_digits) else 0.0)
    dimensions["cta_quality"] = round(cta_score, 1)
    if not has_verb:
        issues.append(QAIssue(
            "weak_cta", "critical",
            "The closing line does not ask the viewer to do anything.",
            "السطر الأخير ما يطلب من الزبون أي خطوة.",
            "استعمل فعل واضح: اتصل، احجز، دز رسالة.",
        ))
    if phone_digits and not contact_shown:
        issues.append(QAIssue(
            "cta_missing_contact", "critical",
            "The call to action never gives the contact number.",
            "الدعوة للتواصل ما بيها رقم الهاتف.",
            "نضيف الرقم بالسطر الأخير وبالكابشن.",
        ))

    # --- real-estate specificity ----------------------------------------
    term_hits = _contains_any(text, REAL_ESTATE_TERMS)
    dimensions["specificity"] = round(min(100.0, 40.0 + len(term_hits) * 12.0), 1)
    if len(term_hits) < 2:
        issues.append(QAIssue(
            "not_specific", "warning",
            "The script says little a buyer can act on (sizes, payments, delivery).",
            "النص ما بيه تفاصيل يهتم بيها المشتري (مساحات، أقساط، تسليم).",
            "أضف رقم أو تفصيل حقيقي من معلومات المشروع.",
        ))

    # --- duration --------------------------------------------------------
    drift = abs(estimated - target)
    dimensions["duration_fit"] = round(max(0.0, 100.0 - (drift / max(target, 1)) * 220.0), 1)
    if drift > target * 0.20:
        longer = estimated > target
        issues.append(QAIssue(
            "duration_mismatch", "warning",
            f"Spoken length {estimated:.0f}s against a {target:.0f}s target.",
            f"المدة المتوقعة {estimated:.0f} ثانية والهدف {target:.0f} ثانية.",
            "نقصّر الجمل." if longer else "نضيف تفصيل مفيد.",
        ))

    weights = {
        "natural_iraqi": 0.20, "msa_free": 0.10, "register": 0.10,
        "no_pressure": 0.12, "clarity": 0.12, "hook_strength": 0.12,
        "rhythm": 0.06, "cta_quality": 0.12, "specificity": 0.03, "duration_fit": 0.03,
    }
    score = round(sum(dimensions.get(k, 80.0) * w for k, w in weights.items()), 1)
    critical = [i for i in issues if i.severity == "critical"]

    return ScriptQAReport(
        score=score,
        dimensions=dimensions,
        issues=issues,
        rewrite_needed=bool(critical) or score < 82.0,
        word_count=len(words),
        estimated_duration_sec=estimated,
        target_duration_sec=target,
    )


# --------------------------------------------------------------------------
# Repair
# --------------------------------------------------------------------------
def improve_script(
    script: Dict[str, Any],
    report: ScriptQAReport,
    *,
    preset: str = "iraqi_professional",
    brand: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """Apply the fixes we can make safely, and say which ones we made.

    Only deterministic edits: soften MSA, drop forbidden claims, shorten a
    runaway line, and repair a CTA that asks for nothing. Anything that needs
    real judgement is left for the writer — a bad automatic rewrite is worse
    than an honest flag.
    """
    brand = brand or {}
    preset_config = D.preset(preset)
    improved = {**script, "lines": [dict(line) for line in (script.get("lines") or [])]}
    changes: List[str] = []
    codes = {issue.code for issue in report.issues}

    forbidden = tuple(
        list(PRESSURE_MARKERS)
        + list(brand.get("forbidden_phrases") or [])
        + list(preset_config.get("forbidden") or [])
    )
    preferred = list(brand.get("preferred_phrases") or []) + list(preset_config.get("preferred") or [])

    def clean(value: str) -> str:
        result = value or ""
        if "unnecessary_msa" in codes:
            result = soften_msa(result)
        for phrase in forbidden:
            if phrase and phrase in result:
                replacement = preferred[0] if preferred else ""
                result = result.replace(phrase, replacement)
        for marker in HEDGE_MARKERS:
            result = result.replace(f"{marker} ", "")
        return re.sub(r"\s{2,}", " ", result).strip(" ،-—")

    for key in ("hook", "body", "cta", "voice_over_text"):
        if improved.get(key):
            new_value = clean(str(improved[key]))
            if new_value != improved[key]:
                improved[key] = new_value
                changes.append(f"cleaned:{key}")

    for index, line in enumerate(improved["lines"]):
        original = line.get("voice_line") or ""
        cleaned = clean(original)
        # A line nobody can say in one breath gets split at its natural seam.
        if len(cleaned.split()) > 16:
            words = cleaned.split()
            midpoint = len(words) // 2
            cleaned = " ".join(words[:midpoint]) + "، " + " ".join(words[midpoint:])
            changes.append(f"split_line:{index}")
        if cleaned != original:
            line["voice_line"] = cleaned
            if line.get("on_screen_text"):
                line["on_screen_text"] = D.to_on_screen(cleaned)
            changes.append(f"cleaned_line:{index}")

    # CTA repair: give it a verb, and the number if the brand has one.
    if "weak_cta" in codes or "cta_missing_contact" in codes:
        phone = str(brand.get("phone") or "").strip()
        closer = (preset_config.get("closers") or ["اتصل بينا هسه"])[0]
        cta = (improved.get("cta") or "").strip()
        if not _contains_any(cta, CTA_VERBS):
            cta = closer if not cta else f"{cta} — {closer}"
        if phone and re.sub(r"\D", "", phone) not in re.sub(r"\D", "", cta):
            cta = f"{cta} · {phone}"
        improved["cta"] = cta
        if improved["lines"]:
            last = improved["lines"][-1]
            last["voice_line"] = cta
            last["on_screen_text"] = cta
        changes.append("repaired_cta")

    if improved["lines"]:
        improved["voice_over_text"] = " ".join(
            line.get("voice_line", "") for line in improved["lines"]
        ).strip()
        improved["word_count"] = len(improved["voice_over_text"].split())

    return improved, changes


def qa_pass(
    script: Dict[str, Any],
    *,
    preset: str = "iraqi_professional",
    brand: Optional[Dict[str, Any]] = None,
    target_duration_sec: Optional[float] = None,
) -> Tuple[Dict[str, Any], ScriptQAReport, List[str]]:
    """Review, repair if needed, review again. Returns the final state.

    The second review is what goes on the record: the user should see the
    quality of the script they are actually being shown.
    """
    report = review_script(script, preset=preset, brand=brand,
                           target_duration_sec=target_duration_sec)
    if not report.rewrite_needed:
        return script, report, []
    improved, changes = improve_script(script, report, preset=preset, brand=brand)
    final = review_script(improved, preset=preset, brand=brand,
                          target_duration_sec=target_duration_sec)
    if final.score < report.score:
        # The repair made it worse — keep the original and stay honest.
        log.info("script QA repair rejected: %.1f < %.1f", final.score, report.score)
        return script, report, []
    return improved, final, changes
