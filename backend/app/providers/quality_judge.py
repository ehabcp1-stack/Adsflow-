"""Scene Quality Judge + Retry policy.

Default acceptance threshold: 90/100. Manual approval always allowed.
Retry ladder (never infinite):
    attempt 1 — normal generation
    attempt 2 — optimized prompt
    attempt 3 — adjusted settings, then fallback provider/model
Every attempt respects the Cost Guard.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.core.config import settings

DIMENSIONS = [
    "prompt_compliance",
    "realism",
    "motion_quality",
    "product_accuracy",
    "architecture_accuracy",
    "human_anatomy",
    "artifacts",
    "camera",
    "lighting",
    "brand_fit",
    "continuity",
]


@dataclass
class QualityVerdict:
    score: float
    breakdown: Dict[str, float]
    passed: bool
    issues: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {"score": self.score, "breakdown": self.breakdown, "passed": self.passed, "issues": self.issues}


def judge_scene(
    *,
    scene: Dict[str, Any],
    result_meta: Dict[str, Any],
    attempt: int = 1,
    threshold: Optional[float] = None,
) -> QualityVerdict:
    """Deterministic mock judge; swap for a real vision model later."""
    threshold = threshold or settings.SCENE_QUALITY_THRESHOLD
    seed = f"{scene.get('id', scene.get('scene_number'))}-{attempt}"
    rng = random.Random(int(hashlib.md5(seed.encode()).hexdigest()[:8], 16))

    base = float(result_meta.get("quality_hint") or rng.uniform(84, 96))
    # Owned media is inherently accurate; generated media carries more risk.
    if scene.get("production_method") in ("original_video", "original_photo", "photo_motion", "motion_graphics"):
        base = max(base, 93.0)
    base += min(attempt - 1, 2) * 2.0  # optimized prompts improve results

    breakdown: Dict[str, float] = {}
    for dim in DIMENSIONS:
        jitter = rng.uniform(-6, 5)
        if dim == "architecture_accuracy" and scene.get("production_method") == "ai_video":
            jitter -= 3
        breakdown[dim] = round(min(99.0, max(55.0, base + jitter)), 1)

    score = round(sum(breakdown.values()) / len(breakdown), 1)
    issues = [f"{dim} below threshold" for dim, val in breakdown.items() if val < 75]
    return QualityVerdict(score=score, breakdown=breakdown, passed=score >= threshold, issues=issues)


@dataclass
class RetryPlan:
    should_retry: bool
    next_attempt: int
    strategy: str
    strategy_ar: str
    switch_provider: bool = False


def plan_retry(*, attempt: int, max_attempts: int, budget_ok: bool) -> RetryPlan:
    if not budget_ok:
        return RetryPlan(False, attempt, "budget_stop", "توقف: الميزانية ما تسمح بإعادة توليد")
    if attempt >= max_attempts:
        return RetryPlan(False, attempt, "manual_review", "وصلنا الحد الأعلى للمحاولات — يحتاج قرار يدوي")
    if attempt == 1:
        return RetryPlan(True, 2, "optimize_prompt", "تحسين البرومبت وإعادة المحاولة")
    return RetryPlan(True, attempt + 1, "adjust_settings_and_fallback", "تغيير الإعدادات والانتقال لمزود بديل", True)
