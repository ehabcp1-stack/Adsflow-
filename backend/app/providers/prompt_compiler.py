"""Prompt Compiler.

RULE: the user-facing script is NEVER sent straight to a video provider.
Production prompts are compiled from structured scene information and then
serialised per provider family.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

BASE_NEGATIVE = [
    "distorted architecture",
    "warped windows",
    "extra fingers",
    "malformed hands",
    "unreadable text",
    "fake arabic letters",
    "watermark",
    "logo artifacts",
    "oversaturated hdr",
    "plastic skin",
]

REALISM_BY_QUALITY = {
    "economy": "clean commercial realism, simple lighting",
    "smart_premium": "photoreal commercial cinematography, 35mm look, natural micro-contrast",
    "maximum_quality": "high-end cinematic realism, anamorphic feel, film grain, art-directed lighting",
}


def compile_scene_prompt(
    *,
    scene: Dict[str, Any],
    project: Dict[str, Any],
    concept: Dict[str, Any] | None = None,
    brand: Dict[str, Any] | None = None,
    quality_level: str = "smart_premium",
    reference_urls: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Structured, provider-agnostic prompt object."""
    brand = brand or {}
    concept = concept or {}
    fidelity_locked = project.get("architecture_fidelity_lock", True) or project.get("product_fidelity_lock", True)

    constraints = [
        "vertical 9:16 framing with safe margins for captions",
        "no on-screen text rendered by the model (captions are added by our editor)",
        "single continuous shot, no cuts",
    ]
    if fidelity_locked and reference_urls:
        constraints.append(
            "match the referenced real project exactly: do not invent facades, floor counts, "
            "materials, signage or landscaping that are not visible in the reference"
        )
    elif fidelity_locked:
        constraints.append(
            "generic architecture only — must not depict a specific real building unless a reference is supplied"
        )

    prompt: Dict[str, Any] = {
        "subject": scene.get("visual_direction") or scene.get("purpose", ""),
        "environment": f"{project.get('category', 'real_estate')} — {project.get('name', '')}",
        "composition": scene.get("purpose", ""),
        "camera": scene.get("camera_direction", ""),
        "lens_feel": "35mm f/2 shallow depth" if quality_level != "economy" else "28mm f/4 clean",
        "movement": scene.get("camera_movement", ""),
        "lighting": scene.get("lighting", ""),
        "motion": "subtle, physically plausible motion; no morphing",
        "timing": {
            "start": scene.get("start_time", 0),
            "end": scene.get("end_time", 0),
            "duration_sec": round(float(scene.get("end_time", 0)) - float(scene.get("start_time", 0)), 2),
        },
        "realism": REALISM_BY_QUALITY.get(quality_level, REALISM_BY_QUALITY["smart_premium"]),
        "style": concept.get("visual_style", ""),
        "brand_palette": [brand.get("primary_color"), brand.get("secondary_color")],
        "constraints": constraints,
        "reference_instructions": (
            "use the supplied project references as the source of truth for geometry and materials"
            if reference_urls
            else "no references supplied"
        ),
        "references": reference_urls or [],
        "negative": BASE_NEGATIVE + (["invented building details"] if fidelity_locked else []),
        # editor-side metadata (never sent to the model as text to render)
        "on_screen_text": scene.get("on_screen_text", ""),
        "scene_label": f"Scene {scene.get('scene_number', 1)}",
        "badge": scene.get("production_method", "").upper().replace("_", " ")[:20],
    }
    return prompt


def serialize_for_provider(prompt: Dict[str, Any], provider: str) -> str:
    """Different compilation strategies per provider family."""
    core = [
        prompt.get("subject", ""),
        prompt.get("environment", ""),
        prompt.get("composition", ""),
        f"camera: {prompt.get('camera','')} {prompt.get('movement','')}",
        f"lighting: {prompt.get('lighting','')}",
        prompt.get("realism", ""),
        prompt.get("style", ""),
    ]
    body = ", ".join([part for part in core if part])
    constraints = "; ".join(prompt.get("constraints", []))
    negative = ", ".join(prompt.get("negative", []))

    if provider in ("veo", "seedance"):
        return f"{body}. Constraints: {constraints}. Avoid: {negative}."
    if provider == "runway":
        return f"{body} | motion: {prompt.get('motion','')} | avoid: {negative}"
    if provider in ("openai", "gemini"):
        return f"{body}.\nConstraints: {constraints}.\nDo not include: {negative}."
    # mock and unknown providers get the readable form
    return f"{body}. [{constraints}]"
