"""Iraqi Dialect Engine — a core differentiator, not a translation layer.

The spoken voice-over script and the written on-screen Arabic are produced
separately: Iraqi speech is written the way people actually talk, while
on-screen text stays short, clean and readable.

Architecture prepared for: pronunciation rules, project-name pronunciation,
number pronunciation, brand-name pronunciation, forbidden/preferred phrases
and tone rules — all overridable per Brand Kit.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app.core.enums import Dialect, StrategicAngle

# --------------------------------------------------------------------------
# Presets
# --------------------------------------------------------------------------
DIALECT_PRESETS: Dict[str, Dict[str, Any]] = {
    Dialect.IRAQI_PROFESSIONAL.value: {
        "label_ar": "عراقي احترافي",
        "label_en": "Iraqi Professional",
        "tone_rules": [
            "وضوح قبل كل شي، بدون مبالغة",
            "جُمل قصيرة تنقرأ بنفَس واحد",
            "بدون كلمات فصحى ثقيلة",
        ],
        "preferred": ["شوف", "هسه", "بكل بساطة", "نوفرلك", "تكدر تحجز", "بمكان مدروس"],
        "forbidden": ["حصرياً وبلا منازع", "الأفضل على الإطلاق", "مجاناً تماماً"],
        "openers": ["شوف هالشي", "خلي أكلك بصراحة", "بيتك الجديد أقرب مما تتصور"],
        "closers": ["احجز موعدك اليوم", "تواصل ويانا وتعرف التفاصيل"],
        "energy": 0.55,
    },
    Dialect.IRAQI_LUXURY.value: {
        "label_ar": "عراقي فخم",
        "label_en": "Iraqi Luxury",
        "tone_rules": ["إيقاع هادئ", "كلمات قليلة وثقيلة المعنى", "بدون صراخ إعلاني"],
        "preferred": ["هدوء", "تفاصيل مشغولة بعناية", "مساحة تليق بيك", "عنوان يتكلم عنك"],
        "forbidden": ["رخيص", "عرض ناري", "استعجل الحين"],
        "openers": ["أكو أماكن ما تحتاج وصف", "بعض العناوين تتكلم عن صاحبها"],
        "closers": ["زورنا وشوفها بعينك", "خلي العنوان يعرّف بيك"],
        "energy": 0.4,
    },
    Dialect.IRAQI_EMOTIONAL.value: {
        "label_ar": "عراقي عاطفي",
        "label_en": "Iraqi Emotional",
        "tone_rules": ["ابدأ من إحساس الناس مو من المواصفات", "استخدم صيغة المخاطب", "دفء بصوت واطي"],
        "preferred": ["بيت يجمعكم", "ضحكة أطفال", "أمان", "تعب السنين", "أخيراً"],
        "forbidden": ["استثمار مضمون", "أرباح خيالية"],
        "openers": ["كل يوم تكول: باچر إن شاء الله", "شنو أحلى من بيت يجمع العايلة"],
        "closers": ["خل باچر يصير اليوم", "بيتكم ينتظركم"],
        "energy": 0.6,
    },
    Dialect.IRAQI_DIRECT_SALES.value: {
        "label_ar": "عراقي مبيعات مباشر",
        "label_en": "Iraqi Direct Sales",
        "tone_rules": ["الرقم والعرض بأول ٣ ثواني", "فعل أمر واضح بالنهاية", "بدون حشو"],
        "preferred": ["أقساط مريحة", "تسليم فوري", "بسعر يناسبك", "الوحدات محدودة"],
        "forbidden": ["ربما", "قد يكون", "تقريباً"],
        "openers": ["دفعة أولى وتستلم مفتاحك", "العرض ينتهي هالأسبوع"],
        "closers": ["اتصل بينا هسه", "دز رسالة وتوصلك التفاصيل"],
        "energy": 0.8,
    },
    Dialect.IRAQI_FRIENDLY.value: {
        "label_ar": "عراقي ودود",
        "label_en": "Iraqi Friendly",
        "tone_rules": ["حچي طبيعي مثل صديق", "سؤال بالبداية", "ابتسامة بالصوت"],
        "preferred": ["هلا بيك", "تعال شوف", "بصراحة", "وياك خطوة بخطوة"],
        "forbidden": ["سيادتكم", "يشرفنا التكرم"],
        "openers": ["هلا بيك، عندي إلك خبر زين", "تدور على بيت مناسب؟"],
        "closers": ["راسلنا وإحنا بالخدمة", "تعال زورنا وشوف بنفسك"],
        "energy": 0.65,
    },
    Dialect.IRAQI_YOUTH.value: {
        "label_ar": "عراقي شبابي",
        "label_en": "Iraqi Youth",
        "tone_rules": ["إيقاع سريع", "قطع كل ثانيتين", "كلمات خفيفة"],
        "preferred": ["فد شوفة", "چان حلو", "خطية لا تفوتها", "وايد حلو"],
        "forbidden": ["وفقاً للمعايير", "بموجب"],
        "openers": ["وقف! شوف هذا", "٣ ثواني وتعرف ليش"],
        "closers": ["سويلها سيف", "الرابط بالبايو"],
        "energy": 0.85,
    },
    Dialect.NONE.value: {
        "label_ar": "بدون لهجة",
        "label_en": "No dialect",
        "tone_rules": ["فصحى واضحة"],
        "preferred": [],
        "forbidden": [],
        "openers": ["اكتشف الفرصة"],
        "closers": ["تواصل معنا"],
        "energy": 0.5,
    },
}

#: Angle → preferred dialect preset (used by the Creative Strategist).
ANGLE_TO_DIALECT: Dict[str, str] = {
    StrategicAngle.EMOTIONAL.value: Dialect.IRAQI_EMOTIONAL.value,
    StrategicAngle.LUXURY.value: Dialect.IRAQI_LUXURY.value,
    StrategicAngle.DIRECT_RESPONSE.value: Dialect.IRAQI_DIRECT_SALES.value,
    StrategicAngle.LIFESTYLE.value: Dialect.IRAQI_FRIENDLY.value,
    StrategicAngle.INVESTMENT.value: Dialect.IRAQI_PROFESSIONAL.value,
    StrategicAngle.INFORMATION_OFFER.value: Dialect.IRAQI_DIRECT_SALES.value,
    StrategicAngle.UGC_LIKE.value: Dialect.IRAQI_FRIENDLY.value,
    StrategicAngle.AUTHORITY_TRUST.value: Dialect.IRAQI_PROFESSIONAL.value,
}

# --------------------------------------------------------------------------
# Pronunciation architecture
# --------------------------------------------------------------------------
ARABIC_ONES = ["صفر", "واحد", "اثنين", "ثلاثة", "أربعة", "خمسة", "ستة", "سبعة", "ثمانية", "تسعة"]
ARABIC_TENS = {
    10: "عشرة", 20: "عشرين", 30: "ثلاثين", 40: "أربعين", 50: "خمسين",
    60: "ستين", 70: "سبعين", 80: "ثمانين", 90: "تسعين",
}


def spell_number_iraqi(value: int) -> str:
    """Number pronunciation for the voice-over layer (not for on-screen text)."""
    if value < 0:
        return str(value)
    if value < 10:
        return ARABIC_ONES[value]
    if value in ARABIC_TENS:
        return ARABIC_TENS[value]
    if value < 100:
        tens, ones = (value // 10) * 10, value % 10
        return f"{ARABIC_ONES[ones]} و{ARABIC_TENS[tens]}"
    if value == 100:
        return "مية"
    if value < 1000:
        hundreds, rest = value // 100, value % 100
        head = "مية" if hundreds == 1 else ("ميتين" if hundreds == 2 else f"{ARABIC_ONES[hundreds]}مية")
        return head if rest == 0 else f"{head} و{spell_number_iraqi(rest)}"
    if value % 1000 == 0:
        thousands = value // 1000
        if thousands == 1:
            return "ألف"
        if thousands == 2:
            return "ألفين"
        return f"{spell_number_iraqi(thousands)} آلاف"
    return f"{spell_number_iraqi(value // 1000)} ألف و{spell_number_iraqi(value % 1000)}"


PHONE_DIGITS = {"0": "صفر", "1": "واحد", "2": "اثنين", "3": "ثلاثة", "4": "أربعة",
                "5": "خمسة", "6": "ستة", "7": "سبعة", "8": "ثمانية", "9": "تسعة"}


def spell_phone(number: str) -> str:
    digits = re.sub(r"\D", "", number)
    return " ".join(PHONE_DIGITS.get(d, d) for d in digits)


def build_pronunciation_guide(
    *,
    project_name: str,
    brand_name: Optional[str] = None,
    phone: Optional[str] = None,
    numbers: Optional[List[int]] = None,
    overrides: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Structured guide handed to the Voice provider adapter."""
    guide: Dict[str, Any] = {
        "project_name": {"written": project_name, "spoken": project_name},
        "brand_name": {"written": brand_name or "", "spoken": brand_name or ""},
        "phone": {"written": phone or "", "spoken": spell_phone(phone) if phone else ""},
        "numbers": {str(n): spell_number_iraqi(n) for n in (numbers or [])},
        "overrides": overrides or {},
    }
    for written, spoken in (overrides or {}).items():
        guide["overrides"][written] = spoken
    return guide


# --------------------------------------------------------------------------
# Style helpers
# --------------------------------------------------------------------------
def preset(name: str) -> Dict[str, Any]:
    return DIALECT_PRESETS.get(name, DIALECT_PRESETS[Dialect.IRAQI_PROFESSIONAL.value])


def list_presets() -> List[Dict[str, Any]]:
    return [{"id": key, **value} for key, value in DIALECT_PRESETS.items()]


def check_forbidden(text: str, extra_forbidden: Optional[List[str]] = None, preset_name: str = "") -> List[str]:
    banned = list(preset(preset_name).get("forbidden", [])) + list(extra_forbidden or [])
    return [phrase for phrase in banned if phrase and phrase in text]


def to_on_screen(spoken: str, max_words: int = 6) -> str:
    """On-screen Arabic is written, not spoken: shorter and cleaner."""
    cleaned = re.sub(r"[،؛!؟.]+", " ", spoken)
    cleaned = re.sub(r"\b(هسه|فد|چان|شوف|هلا بيك|بصراحة|خلي أكلك)\b", " ", cleaned)
    words = [w for w in cleaned.split() if w]
    return " ".join(words[:max_words]).strip()


def estimate_speech_seconds(text: str, speed: float = 1.0) -> float:
    """~2.6 Arabic words/second at natural advertising pace."""
    words = max(len(text.split()), 1)
    return round(words / (2.6 * max(speed, 0.5)), 2)


# --------------------------------------------------------------------------
# Gulf is not Iraqi
# --------------------------------------------------------------------------
#: The gap this closes: `script_qa.MSA_TO_IRAQI` catches Standard Arabic, and
#: a model drifting into *Gulf* Arabic slips past it untouched — every word is
#: colloquial, none of it is Iraqi. The user's words: "النص يستخدم الخليجي
#: أكثر من العراقي".
#:
#: Deliberately conservative. A word goes in only when it is clearly Gulf AND
#: clearly not current Iraqi usage, because a false flag on a word an Iraqi
#: does say costs more trust than a missed one. Shared words — زين، بس، ترى،
#: كشخة، شرايك، صج — are left out on purpose even though they read as Gulf to
#: a non-Iraqi ear. Grow this from real flagged output, never from a guess.
GULF_TO_IRAQI: Dict[str, str] = {
    # wanting
    "أبغى": "أريد",
    "ابغى": "أريد",
    "أبي": "أريد",
    "تبغى": "تريد",
    "تبي": "تريد",
    "يبغى": "يريد",
    "يبي": "يريد",
    "نبغى": "نريد",
    "نبي": "نريد",
    # quantity and time
    "وايد": "هواي",
    "الحين": "هسه",
    "عقب": "بعد",
    # question words
    "ويش": "شنو",
    "وش": "شنو",
    "شفيك": "شبيك",
    "وش فيه": "شبيه",
    "كيفك": "شلونك",
    # manner and linking
    "كذا": "جِذي",
    "چذي": "جِذي",
    "علشان": "حتى",
    "عشان": "حتى",
    "مب": "مو",
    "هني": "هنا",
    # ability
    "يمديك": "تكدر",
    "يمدي": "يكدر",
    "ما يمديك": "ما تكدر",
    # Gulf courtesy that an Iraqi ad does not use
    "لا هنت": "ما تقصّر",
    "لاهنت": "ما تقصّر",
    "طال عمرك": "",
    "دام عزك": "",
    "أبشر": "",
    "ابشر": "",
    "يا بعد قلبي": "",
    # Gulf/pan-Arab ad clichés that read as imported
    "بادر بالحجز": "احجز هسه",
    "تملك الآن": "امتلك هسه",
    "سارع بالحجز": "احجز هسه",
}


@dataclass(frozen=True)
class DialectFlag:
    """One occurrence of a word the script should not be using.

    `suggest` may be empty: some Gulf courtesies have no Iraqi equivalent and
    the right repair is to delete them.

    `start`/`end` are character offsets into the text that was searched. The
    screen replaces **by offset**, never by searching for the word again in
    JavaScript: Arabic word boundaries need a lookbehind that older Safari
    does not have, and a second implementation of this matching would be free
    to disagree with this one. One occurrence, one flag, one exact span.
    """

    found: str
    suggest: str
    kind: str          # gulf | msa | forbidden
    reason_ar: str
    reason_en: str
    start: int = -1
    end: int = -1

    def as_dict(self) -> Dict[str, Any]:
        return {
            "found": self.found,
            "suggest": self.suggest,
            "kind": self.kind,
            "reason_ar": self.reason_ar,
            "reason_en": self.reason_en,
            "start": self.start,
            "end": self.end,
        }


#: What counts as "inside a word" when deciding whether a flagged word
#: really stands alone. Python's ``\w`` is already Unicode-aware, so every
#: Arabic letter and digit is in it; the added range keeps combining
#: diacritics attached to the letter they sit on.
#:
#: The first version of this named the whole Arabic block, which silently
#: swallows the Arabic comma «،» (U+060C) and question mark «؟»
#: (U+061F) — they live in that block too. Any flagged word that ended a
#: clause was therefore invisible: "بادر بالحجز، لا هنت" produced no flags
#: at all — and the end of a line is exactly where an ad's call to action,
#: and its imported Gulf wording, sits.
ARABIC_WORD = "[\\w\\u064B-\\u0652\\u0670]"


def _spans(needle: str, haystack: str, *, whole_word: bool = True) -> List[Tuple[int, int]]:
    """Where `needle` occurs, matched on word boundaries by default.

    Arabic has no case, but it does have prefixes: a bare `\b` still matches
    inside a longer word once و/ب/ال is attached, which is how a naive check
    flags half the script. Multi-word brand phrases are matched as written
    instead, because their edges are not always word edges.
    """
    if not needle:
        return []
    body = re.escape(needle)
    pattern = rf"(?<!{ARABIC_WORD}){body}(?!{ARABIC_WORD})" if whole_word else body
    return [match.span() for match in re.finditer(pattern, haystack)]


def _whole_word(needle: str, haystack: str) -> bool:
    return bool(_spans(needle, haystack))


def find_non_iraqi(
    text: str,
    *,
    preset_name: str = "",
    extra_forbidden: Optional[List[str]] = None,
) -> List[DialectFlag]:
    """Every word in `text` that is not Iraqi, with what to put instead.

    This is what the script screen shows the user. It does not rewrite
    anything: the point is that he can see each word and decide for himself,
    because he is the one who knows how people talk where the ad will run.

    Every occurrence is returned, not one per word — the screen offers the
    swap where the word actually is, and a word said twice is two decisions.
    Longer entries claim their characters first, so "وش فيه" is one flag and
    not a phrase plus the "وش" sitting inside it.
    """
    from app.services.script_qa import MSA_TO_IRAQI

    candidates: List[Tuple[str, str, str, bool]] = []
    for gulf, iraqi in GULF_TO_IRAQI.items():
        candidates.append((gulf, iraqi, "gulf", True))
    for msa, iraqi in MSA_TO_IRAQI.items():
        if iraqi:
            candidates.append((msa, iraqi, "msa", True))
    for phrase in list(preset(preset_name).get("forbidden", [])) + list(extra_forbidden or []):
        if phrase:
            candidates.append((phrase, "", "forbidden", False))
    candidates.sort(key=lambda item: -len(item[0]))

    flags: List[DialectFlag] = []
    claimed: List[Tuple[int, int]] = []
    for needle, suggest, kind, whole_word in candidates:
        for start, end in _spans(needle, text, whole_word=whole_word):
            if any(start < busy_end and busy_start < end for busy_start, busy_end in claimed):
                continue
            claimed.append((start, end))
            if kind == "gulf":
                reason_ar = f"«{needle}» خليجية — بالعراقي {'«' + suggest + '»' if suggest else 'تنشال'}"
                reason_en = f"'{needle}' is Gulf Arabic, not Iraqi"
            elif kind == "msa":
                reason_ar = f"«{needle}» فصحى — بالعراقي «{suggest}»"
                reason_en = f"'{needle}' is Standard Arabic, not Iraqi"
            else:
                reason_ar = f"«{needle}» ممنوعة بهوية العلامة"
                reason_en = f"'{needle}' is on the brand's forbidden list"
            flags.append(DialectFlag(
                found=needle, suggest=suggest, kind=kind,
                reason_ar=reason_ar, reason_en=reason_en, start=start, end=end,
            ))
    return sorted(flags, key=lambda flag: flag.start)


def replace_word(text: str, found: str, suggest: str) -> str:
    """Swap one flagged word for its Iraqi form, on word boundaries."""
    pattern = rf"(?<![\w\u0600-\u06FF]){re.escape(found)}(?![\w\u0600-\u06FF])"
    replaced = re.sub(pattern, suggest, text)
    return re.sub(r"\s{2,}", " ", replaced).strip()


def soften_gulf(text: str) -> str:
    """Apply every Gulf→Iraqi swap. Used by the automatic repair pass."""
    result = text
    for gulf, iraqi in sorted(GULF_TO_IRAQI.items(), key=lambda kv: -len(kv[0])):
        result = replace_word(result, gulf, iraqi)
    return result


def iraqi_writing_rules(preset_name: str = "") -> str:
    """The dialect instruction the model actually receives.

    It used to receive one clause — "Iraqi-Arabic-first" — and nothing that
    says what Iraqi *is*. A model given that will write the Gulf Arabic it has
    far more of, and every word it produces is colloquial enough to look like
    it complied. Naming the neighbours to avoid, listing the swaps and showing
    real lines is the difference.
    """
    rules = preset(preset_name)
    banned = "، ".join(list(GULF_TO_IRAQI)[:14])
    swaps = "، ".join(f"{g}→{i}" for g, i in list(GULF_TO_IRAQI.items())[:10] if i)
    preferred = "، ".join(rules.get("preferred", [])[:6])
    forbidden = "، ".join(rules.get("forbidden", [])[:6])
    return (
        "اكتب بالعراقي المحكي (بغدادي/رافديني) — مو خليجي، مو شامي، مو مصري، مو فصحى.\n"
        f"ممنوع منعاً باتاً هذي الكلمات الخليجية: {banned}.\n"
        f"البدائل العراقية: {swaps}.\n"
        "استعمل: هسه، أكو، ماكو، شلون، وين، هواي، تكدر، خوش، شوف، خلي، هاي، وياك.\n"
        f"أسلوب «{rules.get('label_ar', '')}»: {'، '.join(rules.get('tone_rules', []))}.\n"
        + (f"كلمات مفضّلة: {preferred}.\n" if preferred else "")
        + (f"كلمات ممنوعة: {forbidden}.\n" if forbidden else "")
        + "أمثلة على الإيقاع المطلوب: «شوف هالشي — بيتك الجديد أقرب مما تتصور» · "
          "«أكو وحدات محدودة، وتكدر تحجز هسه بدفعة أولى مريحة»."
    )
