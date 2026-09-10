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
from typing import Any, Dict, List, Optional

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
