"""Motion graphics scenes — offer cards, price panels, info slates.

An offer scene ("25% down, 4 years to pay") should never be an AI-generated
video. It is typography, and typography is cheap, exact and on-brand. This
module renders those scenes as designed cards and animates them with a gentle
push so they sit naturally between filmed shots.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from PIL import Image, ImageDraw, ImageFilter

from app.media.captions import (
    _font,
    _rgba,
    contains_arabic,
    normalize_caption_text,
    resolve_arabic_font,
    resolve_latin_font,
    shape_for_draw,
)
from app.media.ffmpeg import OUT_FPS, OUT_HEIGHT, OUT_WIDTH, ensure_parent
from app.media.motion import render_photo_motion

log = logging.getLogger("adflow.media.motion_graphics")

CARD_TEMPLATES = [
    {"key": "offer_panel", "label_en": "Offer Panel", "label_ar": "لوحة عرض"},
    {"key": "info_slate", "label_en": "Info Slate", "label_ar": "لوحة معلومات"},
    {"key": "price_focus", "label_en": "Price Focus", "label_ar": "تركيز على السعر"},
]


def _text_width(draw: ImageDraw.ImageDraw, text: str, font) -> float:
    shaped, kwargs = shape_for_draw(text) if contains_arabic(text) else (text, {})
    return draw.textlength(shaped, font=font, **kwargs)


def _centered(draw: ImageDraw.ImageDraw, text: str, font, y: float, centre: int, fill) -> float:
    shaped, kwargs = shape_for_draw(text) if contains_arabic(text) else (text, {})
    width = draw.textlength(shaped, font=font, **kwargs)
    draw.text((centre - width / 2, y), shaped, font=font, fill=fill, **kwargs)
    return int(sum(font.getmetrics()) * 1.24)


def render_offer_card(
    out_path: str,
    *,
    headline: str,
    lines: Sequence[str] = (),
    footnote: str = "",
    primary_color: str = "#0F172A",
    accent_color: str = "#2563EB",
    text_color: str = "#FFFFFF",
    font_arabic: Optional[str] = None,
    font_latin: Optional[str] = None,
    template: str = "offer_panel",
    width: int = OUT_WIDTH,
    height: int = OUT_HEIGHT,
) -> Dict[str, Any]:
    """Draw a designed offer/info card at full frame size."""
    headline = normalize_caption_text(headline)
    body = [normalize_caption_text(line) for line in lines if normalize_caption_text(line)]
    footnote = normalize_caption_text(footnote)
    if not headline and not body:
        raise ValueError("an offer card needs at least a headline or one line")

    image = Image.new("RGBA", (width, height), _rgba(primary_color, 1.0))
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse(
        [-width * 0.25, height * 0.05, width * 1.25, height * 0.80], fill=_rgba(accent_color, 0.34)
    )
    image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(140)))
    draw = ImageDraw.Draw(image)
    centre = width // 2

    ar_path = resolve_arabic_font(font_arabic)
    la_path = resolve_latin_font(font_latin) or ar_path
    if not ar_path:
        raise RuntimeError("No Arabic-capable font found. Install fonts-noto-core.")

    def pick(text: str, size: int):
        return _font(ar_path if contains_arabic(text) else la_path, size)

    headline_size = 86 if template == "price_focus" else 72
    body_size = 52
    block: List[Any] = []
    if headline:
        block.append(("headline", headline, pick(headline, headline_size)))
    for line in body:
        block.append(("line", line, pick(line, body_size)))
    if footnote:
        block.append(("footnote", footnote, pick(footnote, 38)))

    total_height = sum(int(sum(font.getmetrics()) * (1.34 if kind != "line" else 1.5))
                       for kind, _, font in block)
    y = (height - total_height) / 2

    # A soft panel keeps the type legible whatever colour the brand uses.
    pad = 54
    max_width = max(_text_width(draw, text, font) for _, text, font in block)
    panel_w = min(width - 110, int(max_width) + pad * 2)
    draw.rounded_rectangle(
        [centre - panel_w // 2, y - pad, centre + panel_w // 2, y + total_height + pad],
        radius=40, fill=_rgba("#000000", 0.26),
    )

    for kind, text, font in block:
        colour = text_color if kind != "footnote" else "#C7D2FE"
        if kind == "headline" and template == "price_focus":
            colour = accent_color if accent_color.lower() != primary_color.lower() else text_color
        advance = _centered(draw, text, font, y, centre, _rgba(colour))
        y += advance * (1.16 if kind == "line" else 1.0)

    ensure_parent(out_path)
    image.convert("RGB").save(out_path, "PNG")
    return {"path": out_path, "template": template, "lines": len(block), "panel_width": panel_w}


def render_offer_scene(
    out_path: str,
    *,
    headline: str,
    lines: Sequence[str] = (),
    footnote: str = "",
    duration_sec: float = 3.5,
    card_path: Optional[str] = None,
    width: int = OUT_WIDTH,
    height: int = OUT_HEIGHT,
    fps: int = OUT_FPS,
    **card_kwargs: Any,
) -> Dict[str, Any]:
    """Render an offer/info card and animate it into a real scene clip."""
    card = card_path or str(Path(out_path).with_suffix(".card.png"))
    card_info = render_offer_card(card, headline=headline, lines=lines, footnote=footnote,
                                  width=width, height=height, **card_kwargs)
    clip = render_photo_motion(
        card, out_path, duration_sec=duration_sec, motion="controlled_zoom",
        look="neutral", width=width, height=height, fps=fps, fade_in=0.25, fade_out=0.25,
    )
    return {**clip, "card": card_info, "production_method": "motion_graphics"}
