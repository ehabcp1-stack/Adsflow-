"""Mock Providers.

Every screen of AdFlow AI must be usable without a single paid API key.
These adapters return realistic, structured Iraqi-Arabic content and real
visual placeholders. They implement exactly the same interfaces as future
real adapters, so replacing them is a one-file change.
"""
from __future__ import annotations

import hashlib
import random
import time
from typing import Any, Dict, List, Optional

from app.core.enums import ProductionMethod, ProductionMode, StrategicAngle
from app.providers.base import (
    ImageProvider,
    LLMProvider,
    MusicProvider,
    ProviderCapability,
    ProviderResult,
    VideoProvider,
    VoiceProvider,
)
from app.providers.pricing import estimate_voice_cost
from app.services import dialect as D
from app.services.media_placeholder import save_clip, save_frame, save_music_audio, save_silent_audio, save_voice_audio


def _rng(seed: str) -> random.Random:
    return random.Random(int(hashlib.md5(seed.encode()).hexdigest()[:8], 16))


# --------------------------------------------------------------------------
# Creative content library (Iraqi Arabic first)
# --------------------------------------------------------------------------
CONCEPT_ARCHETYPES: Dict[str, Dict[str, Any]] = {
    StrategicAngle.EMOTIONAL.value: {
        "name_ar": "بيت يجمعنا",
        "name_en": "A Home That Gathers Us",
        "idea": "الإعلان يبدي من إحساس العائلة بالاستقرار، مو من مواصفات البناء.",
        "hook": "كل يوم تكول: باچر إن شاء الله… خل باچر يصير اليوم.",
        "direction": "لقطات دافئة، ضوء ذهبي قبل الغروب، تفاصيل يومية بسيطة، إيقاع هادئ يتصاعد.",
        "visual_style": "ألوان دافئة، تباين ناعم، عمق ميدان قليل، حركة كاميرا بطيئة.",
        "cta_style": "دعوة هادئة بصوت واطي مع ظهور رقم الهاتف على الشاشة.",
        "why": "جمهور العوائل بالعراق يقرر عاطفياً أول، ويدور على مبرر منطقي بعدين.",
    },
    StrategicAngle.LUXURY.value: {
        "name_ar": "عنوان يليق بيك",
        "name_en": "An Address That Suits You",
        "idea": "المشروع يتقدم كعنوان اجتماعي، مو كوحدة سكنية.",
        "hook": "بعض العناوين ما تحتاج شرح… تكفي شوفة وحدة.",
        "direction": "لقطات واسعة ثابتة، انعكاسات، رخام وإضاءة ليلية، صمت مدروس قبل الجملة.",
        "visual_style": "تدرج بارد مع ذهبي خفيف، تباين عالي، حركة كاميرا محسوبة.",
        "cta_style": "جملة قصيرة وشعار بالنهاية بدون ضغط بيعي.",
        "why": "شريحة الدخل الأعلى تنجذب للهدوء والثقة أكثر من العروض.",
    },
    StrategicAngle.DIRECT_RESPONSE.value: {
        "name_ar": "دفعة أولى ومفتاحك بإيدك",
        "name_en": "First Payment, Keys In Hand",
        "idea": "العرض والسعر والأقساط بأول ثلاث ثواني، وكل شي بعدها دليل.",
        "hook": "دفعة أولى وتستلم مفتاحك… بدون تعقيد.",
        "direction": "قطع سريع، أرقام على الشاشة، لقطات إثبات (موقع، تسليم، نموذج).",
        "visual_style": "ألوان صريحة، نصوص كبيرة، حركة سريعة مضبوطة.",
        "cta_style": "فعل أمر واضح + زر تواصل + تكرار الرقم.",
        "why": "حملات الليدز تحتاج وضوح العرض بأسرع وقت لتقليل كلفة الليد.",
    },
    StrategicAngle.LIFESTYLE.value: {
        "name_ar": "يومك بالمدينة",
        "name_en": "A Day In The City",
        "idea": "نتابع يوم كامل داخل المشروع من الصبح للمساء.",
        "hook": "شلون يصير يومك لو تسكن هنا؟",
        "direction": "مونتاج يوم كامل، حركة طبيعية، أصوات محيط.",
        "visual_style": "طبيعي، ألوان متوازنة، كاميرا محمولة خفيفة.",
        "cta_style": "دعوة للزيارة والتجربة.",
        "why": "يخلي المشتري يتخيل نفسه داخل المكان قبل ما يشوفه.",
    },
    StrategicAngle.INVESTMENT.value: {
        "name_ar": "قرار يزيد قيمته",
        "name_en": "A Decision That Appreciates",
        "idea": "المشروع كفرصة استثمارية بأرقام واقعية بدون وعود مبالغة.",
        "hook": "الموقع اللي تشتريه اليوم… هو سعر باچر.",
        "direction": "لقطات جوية للموقع، خرائط بسيطة، رسوم بيانية نظيفة.",
        "visual_style": "أزرق هادئ، موشن غرافيك دقيق.",
        "cta_style": "طلب استشارة أو كتيب تفاصيل.",
        "why": "شريحة المستثمرين تتحرك بالبيانات والموقع.",
    },
    StrategicAngle.INFORMATION_OFFER.value: {
        "name_ar": "العرض بثلاث نقاط",
        "name_en": "The Offer In Three Points",
        "idea": "ثلاث معلومات فقط: السعر، التسليم، طريقة الحجز.",
        "hook": "ثلاث معلومات وتعرف إذا يناسبك.",
        "direction": "موشن غرافيك مع صور المشروع، إيقاع منتظم.",
        "visual_style": "نظيف، بطاقات نص، ألوان الهوية.",
        "cta_style": "خطوة حجز واحدة واضحة.",
        "why": "أسرع طريقة لتصفية الجمهور غير المهتم وتقليل الكلفة.",
    },
    StrategicAngle.UGC_LIKE.value: {
        "name_ar": "زيارة بدون فلترة",
        "name_en": "An Unfiltered Visit",
        "idea": "شخص يصور زيارته للمشروع بأسلوب طبيعي.",
        "hook": "رحت أشوفها بنفسي… خل أكلكم شصار.",
        "direction": "كاميرا موبايل، حركة يد، كلام عفوي.",
        "visual_style": "واقعي، بدون تلميع زائد.",
        "cta_style": "توصية شخصية + رقم.",
        "why": "المحتوى الطبيعي يرفع نسبة المشاهدة الكاملة على ريلز.",
    },
    StrategicAngle.AUTHORITY_TRUST.value: {
        "name_ar": "شركة تسلّم بالوقت",
        "name_en": "A Developer That Delivers",
        "idea": "الثقة والسجل والتسليم هي الرسالة.",
        "hook": "السؤال مو شنو تشتري… السؤال من منو تشتري.",
        "direction": "لقطات تنفيذ، فريق عمل، مراحل إنجاز.",
        "visual_style": "رصين، تباين متوسط، نصوص واثقة.",
        "cta_style": "دعوة لزيارة المكتب أو الموقع.",
        "why": "بالسوق العراقي الثقة بالمطوّر عامل حسم رئيسي.",
    },
}

GOAL_ANGLES: Dict[str, List[str]] = {
    "leads": [StrategicAngle.EMOTIONAL.value, StrategicAngle.DIRECT_RESPONSE.value, StrategicAngle.LUXURY.value],
    "sales": [StrategicAngle.DIRECT_RESPONSE.value, StrategicAngle.INFORMATION_OFFER.value, StrategicAngle.LUXURY.value],
    "awareness": [StrategicAngle.LIFESTYLE.value, StrategicAngle.EMOTIONAL.value, StrategicAngle.AUTHORITY_TRUST.value],
    "offer": [StrategicAngle.INFORMATION_OFFER.value, StrategicAngle.DIRECT_RESPONSE.value, StrategicAngle.UGC_LIKE.value],
    "launch": [StrategicAngle.LUXURY.value, StrategicAngle.LIFESTYLE.value, StrategicAngle.INVESTMENT.value],
}

SCENE_PURPOSES = [
    ("hook", "الخطّاف — إيقاف التمرير"),
    ("context", "تعريف المكان"),
    ("benefit", "الفائدة الأساسية"),
    ("proof", "إثبات ومصداقية"),
    ("detail", "تفصيل يفرق"),
    ("emotion", "لحظة إحساس"),
    ("offer", "العرض والسعر"),
    ("cta", "الدعوة للتواصل"),
]

CAMERA_MOVES = ["دفع بطيء للأمام", "سحب للخلف", "بان أفقي هادئ", "تتبّع جانبي", "ثابت مع عمق", "ارتفاع بطيء"]
LIGHTING = ["ضوء ذهبي قبل الغروب", "إضاءة ليلية دافئة", "نهار صافي مع ظل ناعم", "إضاءة داخلية متوازنة"]
TRANSITIONS = ["cut", "soft_dissolve", "whip_pan", "match_cut", "speed_ramp"]


class MockLLMProvider(LLMProvider):
    name = "mock"
    is_mock = True

    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            name="mock", kind="llm", models=["mock-llm-v1"], is_mock=True,
            notes="Structured Iraqi Arabic sample outputs. No network, no cost.",
        )

    # -- public -----------------------------------------------------------
    def complete_json(self, *, task: str, context: Dict[str, Any], model: Optional[str] = None) -> ProviderResult:
        started = time.time()
        handler = getattr(self, f"_task_{task}", None)
        if handler is None:
            data: Dict[str, Any] = {"note": f"mock has no handler for task '{task}'", "context_keys": list(context)}
        else:
            data = handler(context)
        return ProviderResult(
            ok=True, provider=self.name, model=model or "mock-llm-v1", operation=task,
            is_mock=True, cost_usd=0.0, latency_ms=int((time.time() - started) * 1000), data=data,
        )

    # -- tasks ------------------------------------------------------------
    def _task_brief_interpretation(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        brief = ctx.get("brief", {})
        name = brief.get("name", "المشروع")
        return {
            "objective": brief.get("goal", "leads"),
            "objective_ar": {
                "leads": "توليد استفسارات وحجوزات",
                "sales": "بيع مباشر",
                "awareness": "تعريف بالمشروع",
                "offer": "إيصال عرض محدد",
                "launch": "إطلاق مشروع جديد",
            }.get(brief.get("goal", "leads"), "توليد استفسارات"),
            "audience_summary": brief.get("target_audience") or "عوائل عراقية ٢٨–٤٥ سنة تدور على سكن مناسب",
            "platform_notes": "ريلز عمودي ٩:١٦، أول ٣ ثواني تقرر نسبة المشاهدة",
            "language_plan": {
                "voice_over": "لهجة عراقية طبيعية",
                "on_screen": "عربي مكتوب مختصر وواضح",
                "numbers": "الأرقام تنقرأ بالصوت وتنكتب بالأرقام على الشاشة",
            },
            "key_messages": [msg.strip() for msg in (brief.get("key_information") or "").split("\n") if msg.strip()][:5]
            or [f"{name} بموقع مدروس", "أقساط مريحة", "تسليم واضح بالوقت"],
            "must_include": [brief.get("cta") or "تواصل معنا"],
            "risk_notes": ["ممنوع تغيير تصميم المشروع الحقيقي بأي لقطة مولدة"],
        }

    def _task_creative_strategy(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        brief = ctx.get("brief", {})
        assets = ctx.get("assets_summary", {})
        goal = brief.get("goal", "leads")
        angles = GOAL_ANGLES.get(goal, GOAL_ANGLES["leads"])
        has_video = assets.get("video_count", 0) > 0
        has_photo = assets.get("image_count", 0) > 0
        if has_video and has_photo:
            mode = ProductionMode.HYBRID_REEL.value
        elif has_video:
            mode = ProductionMode.VIDEO_REMIX_REEL.value
        elif has_photo:
            mode = ProductionMode.PHOTO_VOICE_REEL.value
        else:
            mode = ProductionMode.FULL_AI_REEL.value
        return {
            "recommended_angle": angles[0],
            "alternative_angles": angles[1:],
            "recommended_mode": mode,
            "recommended_voice_style": D.ANGLE_TO_DIALECT.get(angles[0], "iraqi_professional"),
            "marketing_angle_ar": CONCEPT_ARCHETYPES[angles[0]]["idea"],
            "pacing": "قطع كل ٣–٤ ثواني مع لقطة بطل وحدة أطول",
        }

    def _task_concepts(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        brief = ctx.get("brief", {})
        goal = brief.get("goal", "leads")
        name = brief.get("name", "المشروع")
        cta = brief.get("cta") or "تواصل ويانا"
        rng = _rng(f"{name}-{goal}")
        chosen = GOAL_ANGLES.get(goal, GOAL_ANGLES["leads"])
        pool = chosen + [a for a in CONCEPT_ARCHETYPES if a not in chosen]
        concepts: List[Dict[str, Any]] = []
        for index, angle in enumerate(pool[:5]):  # internally more candidates, 3 surfaced
            arch = CONCEPT_ARCHETYPES[angle]
            scores = {
                "goal_fit": round(rng.uniform(72, 96) + (8 if index == 0 else 0), 1),
                "audience_fit": round(rng.uniform(70, 95), 1),
                "asset_fit": round(rng.uniform(68, 96), 1),
                "platform_fit": round(rng.uniform(75, 96), 1),
                "hook_strength": round(rng.uniform(70, 97), 1),
                "voice_suitability": round(rng.uniform(74, 96), 1),
                "cost_efficiency": round(rng.uniform(70, 98), 1),
                "brand_fit": round(rng.uniform(72, 95), 1),
                "originality": round(rng.uniform(62, 93), 1),
                "conversion_potential": round(rng.uniform(70, 96), 1),
            }
            total = round(sum(scores.values()) / len(scores), 1)
            concepts.append(
                {
                    "angle": angle,
                    "name": f"{arch['name_ar']} — {name}",
                    "name_en": arch["name_en"],
                    "one_line_idea": arch["idea"],
                    "hook": arch["hook"],
                    "creative_direction": arch["direction"],
                    "recommended_mode": ctx.get("recommended_mode", ProductionMode.HYBRID_REEL.value),
                    "recommended_voice": D.ANGLE_TO_DIALECT.get(angle, "iraqi_professional"),
                    "visual_style": arch["visual_style"],
                    "cta_style": f"{arch['cta_style']} — «{cta}»",
                    "why_this_works": arch["why"],
                    "scores": scores,
                    "score_total": total,
                    "is_alternative": index >= 3,
                }
            )
        concepts.sort(key=lambda c: (c["is_alternative"], -c["score_total"]))
        if concepts:
            concepts[0]["is_recommended"] = True
        return {"concepts": concepts}

    def _task_script(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        brief = ctx.get("brief", {})
        concept = ctx.get("concept", {})
        variant = ctx.get("variant", "primary")
        duration = float(brief.get("duration_sec", 30))
        name = brief.get("name", "المشروع")
        cta_text = brief.get("cta") or "اتصل بينا اليوم"
        preset_name = concept.get("recommended_voice") or brief.get("dialect") or "iraqi_professional"
        preset = D.preset(preset_name)
        rng = _rng(f"{name}-{variant}-{duration}")

        key_points = [p.strip() for p in (brief.get("key_information") or "").split("\n") if p.strip()]
        if not key_points:
            key_points = ["موقع قريب من كل شي تحتاجه", "تصاميم مدروسة للعائلة", "أقساط مريحة وتسليم واضح"]

        # The project name has to be *said*, not implied: QC treats a reel that
        # never names the project as a real defect, and so does a buyer.
        hook = concept.get("hook") or rng.choice(preset["openers"])
        if name and name not in hook:
            hook = f"{hook} — {name}".strip(" —")
        if variant == "more_sales":
            hook = f"دفعة أولى وتستلم مفتاحك بـ{name}."
        elif variant == "more_emotional":
            hook = f"البيت مو جدران… البيت ناس. و{name} صار مكانهم."

        beats = max(3, min(7, int(duration // 5)))
        body_lines: List[str] = []
        for i in range(beats - 2):
            point = key_points[i % len(key_points)]
            connector = rng.choice(["و", "وهم", "وبنفس الوقت", "والأهم"]) if i else ""
            body_lines.append(f"{connector} {point}".strip())
        if variant == "more_sales":
            body_lines.append("الوحدات محدودة والعرض ينتهي هالأسبوع.")
        elif variant == "more_emotional":
            body_lines.append("تخيل ضحكة أطفالك بأول يوم بالبيت الجديد.")

        # The closing line carries the contact number. An ad that asks people to
        # call without telling them what to call is the most expensive kind of
        # mistake, so the brand phone is spoken and shown when we have one.
        phone = (ctx.get("brand", {}) or {}).get("phone") or ""
        cta_line = f"{cta_text} — {rng.choice(preset['closers'])}"
        if phone:
            cta_line = f"{cta_text} — اتصل على {D.spell_phone(phone)}"

        lines: List[Dict[str, Any]] = []
        cursor = 0.0
        ordered = [("hook", hook)] + [("body", b) for b in body_lines] + [("cta", cta_line)]
        raw_total = sum(D.estimate_speech_seconds(text) for _, text in ordered) or 1.0
        scale = duration / raw_total
        for idx, (role, text) in enumerate(ordered):
            seconds = round(max(1.6, D.estimate_speech_seconds(text) * scale), 2)
            lines.append(
                {
                    "index": idx,
                    "role": role,
                    "voice_line": text,
                    # Spoken and written diverge on purpose: the voice says the
                    # number digit by digit, the screen shows it as digits.
                    "on_screen_text": (
                        f"{cta_text} · {phone}" if (role == "cta" and phone) else D.to_on_screen(text)
                    ),
                    "start": round(cursor, 2),
                    "end": round(min(cursor + seconds, duration), 2),
                }
            )
            cursor = min(cursor + seconds, duration)
        if lines:
            lines[-1]["end"] = duration

        voice_over_text = " ".join(line["voice_line"] for line in lines)
        word_count = len(voice_over_text.split())
        critic: List[str] = []
        if word_count / max(duration, 1) > 2.9:
            critic.append("عدد الكلمات عالي نسبة للمدة — يفضّل تقصير جملة من المتن.")
        if not any(ch.isdigit() for ch in voice_over_text) and brief.get("goal") in ("sales", "offer"):
            critic.append("ما أكو رقم واضح بالنص — أضف السعر أو الدفعة الأولى.")
        forbidden_hits = D.check_forbidden(voice_over_text, ctx.get("forbidden_phrases"), preset_name)
        critic += [f"عبارة ممنوعة بالهوية: «{p}»" for p in forbidden_hits]

        score = round(max(60.0, 96.0 - 6 * len(critic) - rng.uniform(0, 4)), 1)
        return {
            "hook": hook,
            "body": " ".join(body_lines),
            "cta": cta_line,
            "voice_over_text": voice_over_text,
            "on_screen_text": [
                {"index": line["index"], "text": line["on_screen_text"], "start": line["start"], "end": line["end"]}
                for line in lines
            ],
            "lines": lines,
            "dialect_preset": preset_name,
            "total_duration_sec": duration,
            "word_count": word_count,
            "score": score,
            "critic_notes": critic or ["النص متوازن: خطّاف واضح، متن قصير، دعوة مباشرة."],
        }

    def _task_storyboard(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        script = ctx.get("script", {})
        brief = ctx.get("brief", {})
        assets = ctx.get("assets", [])
        rng = _rng(f"sb-{brief.get('name','p')}-{len(assets)}")
        images = [a for a in assets if a.get("kind") == "image" and a.get("usable", True)]
        videos = [a for a in assets if a.get("kind") == "video" and a.get("usable", True)]
        lines = script.get("lines") or []
        scenes: List[Dict[str, Any]] = []
        for idx, line in enumerate(lines):
            purpose_key, purpose_ar = SCENE_PURPOSES[min(idx, len(SCENE_PURPOSES) - 1)]
            if line.get("role") == "hook":
                purpose_key, purpose_ar = SCENE_PURPOSES[0]
            elif line.get("role") == "cta":
                purpose_key, purpose_ar = SCENE_PURPOSES[-1]

            asset = None
            method = ProductionMethod.AI_IMAGE.value
            source = "ai_image"
            if videos and idx % 3 == 0:
                asset = videos[idx % len(videos)]
                method, source = ProductionMethod.ORIGINAL_VIDEO.value, "existing_video"
            elif images:
                asset = images[idx % len(images)]
                method = ProductionMethod.PHOTO_MOTION.value if idx % 2 else ProductionMethod.ORIGINAL_PHOTO.value
                source = "existing_photo"
            elif purpose_key in ("offer", "cta"):
                method, source = ProductionMethod.MOTION_GRAPHICS.value, "motion_graphics"

            scenes.append(
                {
                    "scene_number": idx + 1,
                    "start_time": line.get("start", 0),
                    "end_time": line.get("end", 3),
                    "purpose": purpose_ar,
                    "voice_line": line.get("voice_line", ""),
                    "visual_source": source,
                    "selected_asset_id": (asset or {}).get("id"),
                    "visual_direction": rng.choice(
                        [
                            "لقطة واسعة تعرّف بالمكان مع حركة بطيئة",
                            "لقطة قريبة لتفصيل يعطي إحساس الجودة",
                            "لقطة متوسطة مع عمق وحركة خفيفة",
                            "لقطة علوية تبيّن الموقع والمساحة",
                        ]
                    ),
                    "camera_direction": rng.choice(["أمامية", "جانبية", "علوية", "بمستوى النظر"]),
                    "camera_movement": rng.choice(CAMERA_MOVES),
                    "lighting": rng.choice(LIGHTING),
                    "on_screen_text": line.get("on_screen_text", ""),
                    "text_animation": rng.choice(["fade_up", "mask_reveal", "typewriter", "slide_in"]),
                    "music_instruction": "طبقة موسيقية هادئة تتصاعد" if idx == 0 else "استمرار الطبقة نفسها",
                    "sfx_instruction": rng.choice(["whoosh خفيف", "أصوات محيط طبيعية", "بدون مؤثرات"]),
                    "transition": rng.choice(TRANSITIONS),
                    "production_method": method,
                    "is_hook": idx == 0,
                    "is_hero": idx == 1,
                    "priority": 100 if idx == 0 else (90 if idx == 1 else max(10, 70 - idx * 5)),
                }
            )
        return {"scenes": scenes}

    def _task_qc(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        project = ctx.get("project", {})
        script = ctx.get("script", {})
        brand = ctx.get("brand", {})
        rng = _rng(f"qc-{project.get('id','x')}-{ctx.get('render_version',1)}")
        issues: List[Dict[str, Any]] = []
        vo = script.get("voice_over_text", "")
        if brand.get("phone") and brand["phone"] not in (project.get("cta", "") + vo + str(brand.get("phone"))):
            pass  # phone presence is validated on the render layer
        if not script.get("cta"):
            issues.append({"code": "missing_cta", "severity": "critical", "message_ar": "ما أكو دعوة للتواصل بالنهاية"})
        if project.get("name") and project["name"] not in vo:
            issues.append(
                {"code": "project_name_missing", "severity": "warning",
                 "message_ar": "اسم المشروع ما ينذكر بالتعليق الصوتي"}
            )
        return {
            "scores": {
                "visual_quality": round(rng.uniform(88, 97), 1),
                "audio_voice": round(rng.uniform(86, 96), 1),
                "arabic_quality": round(rng.uniform(88, 98), 1),
                "marketing_effectiveness": round(rng.uniform(85, 96), 1),
                "brand_consistency": round(rng.uniform(88, 99), 1),
                "platform_fit": round(rng.uniform(90, 99), 1),
            },
            "issues": issues,
            "recommendations": [
                {"code": "hook_tighten", "message_ar": "قصّر الخطّاف نصف ثانية لرفع نسبة الاستمرار", "impact": "medium"},
                {"code": "caption_contrast", "message_ar": "زد تباين الكابشن بالمشهد الثالث", "impact": "low"},
            ],
        }

    def _task_refine(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """Refinement instructions never lose the selected concept."""
        action = ctx.get("action", "more_iraqi")
        text = ctx.get("text", "")
        mapping = {
            "more_iraqi": ("هسه ", " — بصراحة"),
            "more_premium": ("", " — بهدوء يليق بيك"),
            "more_direct": ("", " — اتصل بينا هسه"),
            "shorter": ("", ""),
            "stronger_hook": ("وقف ثانية! ", ""),
            "more_emotional": ("", " — لأن العايلة تستاهل"),
            "more_sales": ("", " — أقساط مريحة وتسليم فوري"),
            "more_luxury": ("", " — تفاصيل مشغولة بعناية"),
        }
        prefix, suffix = mapping.get(action, ("", ""))
        if action == "shorter":
            words = text.split()
            refined = " ".join(words[: max(6, int(len(words) * 0.7))])
        else:
            refined = f"{prefix}{text}{suffix}".strip()
        return {"text": refined, "action": action}


class MockImageProvider(ImageProvider):
    name = "mock"
    is_mock = True

    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            name="mock", kind="image", models=["mock-image-v1"], is_mock=True,
            supports_reference_image=True, notes="Generates real SVG placeholder frames.",
        )

    def generate_image(
        self, *, prompt: Dict[str, Any], model: Optional[str] = None,
        reference_urls: Optional[List[str]] = None, aspect_ratio: str = "9:16",
    ) -> ProviderResult:
        started = time.time()
        key = prompt.get("storage_key") or f"mock/images/{hashlib.md5(str(prompt).encode()).hexdigest()[:16]}.svg"
        url = save_frame(
            key,
            seed=str(prompt.get("subject", "")) + key,
            title_ar=str(prompt.get("on_screen_text") or prompt.get("subject", ""))[:40],
            subtitle=str(prompt.get("composition", ""))[:60],
            badge=prompt.get("badge", "AI IMAGE"),
        )
        return ProviderResult(
            ok=True, provider=self.name, model=model or "mock-image-v1", operation="image_generation",
            is_mock=True, cost_usd=0.0, latency_ms=int((time.time() - started) * 1000), url=url,
            quality_hint=round(_rng(key).uniform(88, 97), 1),
            data={"aspect_ratio": aspect_ratio, "references_used": reference_urls or []},
        )


class MockVideoProvider(VideoProvider):
    name = "mock"
    is_mock = True

    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            name="mock", kind="video", models=["mock-video-v1"], is_mock=True,
            supports_image_to_video=True, max_duration_sec=10.0,
            notes="Returns a real short MP4 when FFmpeg is present, else an SVG poster.",
        )

    def generate_video(
        self, *, prompt: Dict[str, Any], model: Optional[str] = None, keyframe_url: Optional[str] = None,
        duration_sec: float = 4.0, aspect_ratio: str = "9:16",
    ) -> ProviderResult:
        started = time.time()
        digest = hashlib.md5(str(prompt).encode()).hexdigest()[:16]
        poster = save_frame(
            f"mock/video/{digest}.svg",
            seed=digest,
            title_ar=str(prompt.get("on_screen_text") or prompt.get("subject", ""))[:40],
            subtitle=str(prompt.get("movement", ""))[:60],
            badge="AI VIDEO",
        )
        clip = save_clip(
            f"mock/video/{digest}.mp4", seed=digest, duration_sec=duration_sec,
            label=str(prompt.get("scene_label", "Scene")),
        )
        return ProviderResult(
            ok=True, provider=self.name, model=model or "mock-video-v1", operation="video_generation",
            is_mock=True, cost_usd=0.0, latency_ms=int((time.time() - started) * 1000),
            url=clip or poster,
            quality_hint=round(_rng(digest).uniform(86, 96), 1),
            data={"poster_url": poster, "clip_url": clip, "duration_sec": duration_sec, "keyframe_url": keyframe_url},
        )


MOCK_VOICES: List[Dict[str, Any]] = [
    {
        "id": "mock-iq-male-pro", "name": "Iraqi Male — Professional", "name_ar": "عراقي رجالي — احترافي",
        "gender": "male", "dialect": "iraqi_professional", "style": "professional",
    },
    {
        "id": "mock-iq-female-premium", "name": "Iraqi Female — Premium", "name_ar": "عراقي نسائي — فخم",
        "gender": "female", "dialect": "iraqi_luxury", "style": "premium",
    },
    {
        "id": "mock-iq-male-emotional", "name": "Iraqi Male — Emotional", "name_ar": "عراقي رجالي — عاطفي",
        "gender": "male", "dialect": "iraqi_emotional", "style": "emotional",
    },
    {
        "id": "mock-iq-female-friendly", "name": "Iraqi Female — Friendly", "name_ar": "عراقي نسائي — ودود",
        "gender": "female", "dialect": "iraqi_friendly", "style": "friendly",
    },
]


class MockVoiceProvider(VoiceProvider):
    name = "mock"
    is_mock = True

    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            name="mock", kind="voice", models=["mock-voice-v1"], is_mock=True,
            notes="Demo Iraqi voice profiles with real timing and a speech-shaped audio track.",
        )

    def list_voices(self) -> List[Dict[str, Any]]:
        return [dict(v, provider="mock", is_demo=True) for v in MOCK_VOICES]

    def synthesize(
        self, *, text: str, voice_id: str, model: Optional[str] = None,
        speed: float = 1.0, energy: float = 0.6, emotion: float = 0.5,
    ) -> ProviderResult:
        started = time.time()
        duration = D.estimate_speech_seconds(text, speed)
        digest = hashlib.md5(f"{voice_id}:{text}:{speed}".encode()).hexdigest()[:16]
        url = save_voice_audio(f"mock/voice/{digest}.m4a", duration)
        return ProviderResult(
            ok=True, provider=self.name, model=model or "mock-voice-v1", operation="voice_generation",
            is_mock=True, cost_usd=0.0, latency_ms=int((time.time() - started) * 1000), url=url,
            data={
                "duration_sec": duration,
                "voice_id": voice_id,
                "characters": len(text),
                "would_cost_with_real_provider_usd": estimate_voice_cost(len(text)),
                "energy": energy,
                "emotion": emotion,
            },
        )


class MockMusicProvider(MusicProvider):
    name = "mock"
    is_mock = True

    def capability(self) -> ProviderCapability:
        return ProviderCapability(name="mock", kind="music", models=["mock-music-v1"], is_mock=True)

    def generate_music(
        self, *, brief: Dict[str, Any], duration_sec: float = 30.0, model: Optional[str] = None
    ) -> ProviderResult:
        started = time.time()
        digest = hashlib.md5(str(brief).encode()).hexdigest()[:16]
        url = save_music_audio(f"mock/music/{digest}.m4a", duration_sec)
        return ProviderResult(
            ok=True, provider=self.name, model=model or "mock-music-v1", operation="music_generation",
            is_mock=True, cost_usd=0.0, latency_ms=int((time.time() - started) * 1000), url=url,
            data={"mood": brief.get("mood", "cinematic warm"), "duration_sec": duration_sec, "bpm": 84},
        )
