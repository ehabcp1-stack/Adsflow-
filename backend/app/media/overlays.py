"""Brand layer: logo, CTA card, end screen and timed overlays.

Everything a customer's ad needs on top of the footage is drawn here with
Pillow and composited by FFmpeg. Two rules matter:

* The brand rendered is the **project's** Brand Kit. AdFlow AI is a TADAFQ
  product, but a customer's ad never carries TADAFQ branding.
* Nothing is drawn outside the platform safe zones, so Instagram and TikTok
  chrome never covers the phone number.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFilter

from app.media.captions import (
    CaptionStyle,
    _font,
    _rgba,
    normalize_caption_text,
    resolve_arabic_font,
    resolve_latin_font,
    shape_for_draw,
    contains_arabic,
)
from app.media.ffmpeg import OUT_HEIGHT, OUT_WIDTH, ensure_parent

log = logging.getLogger("adflow.media.overlays")

LOGO_POSITIONS = ("top_left", "top_right", "bottom_left", "bottom_right")

#: Platform UI keep-out zones as fractions of the frame.
PLATFORM_SAFE_ZONES: Dict[str, Dict[str, float]] = {
    "instagram_reels": {"top": 0.10, "bottom": 0.20, "side": 0.06},
    "facebook_reels": {"top": 0.10, "bottom": 0.20, "side": 0.06},
    "tiktok": {"top": 0.09, "bottom": 0.24, "side": 0.08},
    "multi": {"top": 0.12, "bottom": 0.24, "side": 0.08},
}


def safe_zone(platform: str) -> Dict[str, float]:
    return PLATFORM_SAFE_ZONES.get(platform, PLATFORM_SAFE_ZONES["multi"])


@dataclass
class BrandLayer:
    """Everything the renderer needs from a Brand Kit."""

    name: str = ""
    logo_path: Optional[str] = None
    primary_color: str = "#0F172A"
    secondary_color: str = "#2563EB"
    accent_color: str = "#1D4ED8"
    font_arabic: Optional[str] = None
    font_latin: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    social_handle: Optional[str] = None
    cta_text: str = ""
    tagline: str = ""
    end_screen_template: Dict[str, Any] = field(default_factory=dict)
    logo_position: str = "top_left"
    watermark_opacity: float = 0.85


def _draw_line(draw: ImageDraw.ImageDraw, xy: Tuple[float, float], text: str, font,
               fill, anchor_centre_x: Optional[int] = None, **kwargs: Any) -> float:
    """Draw a single text line with correct direction; returns its width."""
    shaped, draw_kwargs = shape_for_draw(text) if contains_arabic(text) else (text, {})
    width = draw.textlength(shaped, font=font, **draw_kwargs)
    x = (anchor_centre_x - width / 2) if anchor_centre_x is not None else xy[0]
    draw.text((x, xy[1]), shaped, font=font, fill=fill, **draw_kwargs, **kwargs)
    return width


def _pick_font(text: str, brand: BrandLayer, size: int):
    if contains_arabic(text):
        return _font(resolve_arabic_font(brand.font_arabic), size)
    return _font(resolve_latin_font(brand.font_latin) or resolve_arabic_font(brand.font_arabic), size)


def prepare_logo(logo_path: str, out_path: str, *, max_width: int = 260,
                 opacity: float = 0.9) -> Optional[str]:
    """Normalise a customer logo to a size and opacity that never dominates."""
    source = Path(logo_path)
    if not source.exists():
        return None
    try:
        logo = Image.open(source).convert("RGBA")
    except Exception as exc:  # noqa: BLE001
        log.warning("unreadable logo %s: %s", logo_path, exc)
        return None
    ratio = max_width / max(logo.width, 1)
    logo = logo.resize((max_width, max(int(logo.height * ratio), 1)), Image.LANCZOS)
    if opacity < 1.0:
        alpha = logo.getchannel("A").point(lambda v: int(v * opacity))
        logo.putalpha(alpha)
    ensure_parent(out_path)
    logo.save(out_path, "PNG")
    return out_path


def logo_xy(position: str, *, logo_width: int, logo_height: int, platform: str = "multi",
            width: int = OUT_WIDTH, height: int = OUT_HEIGHT) -> Tuple[int, int]:
    zone = safe_zone(platform)
    margin_x = int(width * zone["side"])
    margin_top = int(height * zone["top"] * 0.55)
    margin_bottom = int(height * zone["bottom"] * 0.55)
    if position == "top_right":
        return width - margin_x - logo_width, margin_top
    if position == "bottom_left":
        return margin_x, height - margin_bottom - logo_height
    if position == "bottom_right":
        return width - margin_x - logo_width, height - margin_bottom - logo_height
    return margin_x, margin_top


def render_cta_card(
    out_path: str,
    brand: BrandLayer,
    *,
    cta_text: str,
    platform: str = "instagram_reels",
    width: int = OUT_WIDTH,
    height: int = OUT_HEIGHT,
) -> Dict[str, Any]:
    """A lower-third call-to-action pill with the phone number under it."""
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    zone = safe_zone(platform)

    cta_text = normalize_caption_text(cta_text or brand.cta_text or "")
    phone = normalize_caption_text(brand.phone or "")
    if not cta_text and not phone:
        raise ValueError("CTA card needs text or a phone number")

    cta_font = _pick_font(cta_text or phone, brand, 64)
    phone_font = _pick_font(phone or cta_text, brand, 52)

    block_bottom = height - int(height * zone["bottom"]) - 30
    phone_h = int(sum(phone_font.getmetrics()) * 1.2) if phone else 0
    cta_h = int(sum(cta_font.getmetrics()) * 1.25) if cta_text else 0
    pill_top = block_bottom - phone_h - cta_h - 56

    centre = width // 2
    text_width = 0
    if cta_text:
        shaped, kw = shape_for_draw(cta_text) if contains_arabic(cta_text) else (cta_text, {})
        text_width = max(text_width, int(draw.textlength(shaped, font=cta_font, **kw)))
    if phone:
        shaped, kw = shape_for_draw(phone) if contains_arabic(phone) else (phone, {})
        text_width = max(text_width, int(draw.textlength(shaped, font=phone_font, **kw)))
    pill_w = min(width - int(width * zone["side"]) * 2, text_width + 120)

    draw.rounded_rectangle(
        [centre - pill_w // 2, pill_top, centre + pill_w // 2, block_bottom],
        radius=34,
        fill=_rgba(brand.secondary_color, 0.94),
    )
    y = pill_top + 26
    if cta_text:
        _draw_line(draw, (0, y), cta_text, cta_font, _rgba("#FFFFFF"), anchor_centre_x=centre)
        y += cta_h
    if phone:
        _draw_line(draw, (0, y), phone, phone_font, _rgba("#EAF1FF"), anchor_centre_x=centre)

    ensure_parent(out_path)
    image.save(out_path, "PNG", optimize=True)
    return {
        "path": out_path,
        "pill_top": pill_top,
        "pill_bottom": block_bottom,
        "within_safe_zone": pill_top > int(height * zone["top"]),
    }


def render_end_screen(
    out_path: str,
    brand: BrandLayer,
    *,
    style: str = "logo_center",
    width: int = OUT_WIDTH,
    height: int = OUT_HEIGHT,
) -> Dict[str, Any]:
    """A full-frame closing card: logo, tagline, CTA, phone, website, handle."""
    template = brand.end_screen_template or {}
    style = template.get("style", style)
    background = Image.new("RGBA", (width, height), _rgba(brand.primary_color, 1.0))
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse(
        [-width * 0.3, -height * 0.1, width * 1.3, height * 0.75],
        fill=_rgba(brand.secondary_color, 0.30),
    )
    background.alpha_composite(glow.filter(ImageFilter.GaussianBlur(120)))
    draw = ImageDraw.Draw(background)
    centre = width // 2

    y = int(height * 0.26)
    if brand.logo_path and Path(brand.logo_path).exists():
        try:
            logo = Image.open(brand.logo_path).convert("RGBA")
            target = int(width * 0.36)
            logo = logo.resize((target, max(int(logo.height * target / max(logo.width, 1)), 1)), Image.LANCZOS)
            background.alpha_composite(logo, (centre - logo.width // 2, y))
            y += logo.height + 48
        except Exception as exc:  # noqa: BLE001
            log.warning("end screen logo failed: %s", exc)

    name = normalize_caption_text(brand.name or "")
    if name:
        font = _pick_font(name, brand, 72)
        _draw_line(draw, (0, y), name, font, _rgba("#FFFFFF"), anchor_centre_x=centre)
        y += int(sum(font.getmetrics()) * 1.25)

    tagline = normalize_caption_text(brand.tagline or template.get("tagline", ""))
    if tagline:
        font = _pick_font(tagline, brand, 44)
        _draw_line(draw, (0, y), tagline, font, _rgba("#DCE6FF", 0.92), anchor_centre_x=centre)
        y += int(sum(font.getmetrics()) * 1.4)

    cta = normalize_caption_text(brand.cta_text or template.get("cta", ""))
    if cta:
        font = _pick_font(cta, brand, 56)
        shaped, kw = shape_for_draw(cta) if contains_arabic(cta) else (cta, {})
        pill_w = int(draw.textlength(shaped, font=font, **kw)) + 110
        pill_h = int(sum(font.getmetrics()) * 1.5)
        draw.rounded_rectangle(
            [centre - pill_w // 2, y, centre + pill_w // 2, y + pill_h],
            radius=pill_h // 2, fill=_rgba(brand.secondary_color, 1.0),
        )
        _draw_line(draw, (0, y + pill_h * 0.18), cta, font, _rgba("#FFFFFF"), anchor_centre_x=centre)
        y += pill_h + 44

    contact_lines = [v for v in (brand.phone, brand.website, brand.social_handle) if v]
    for line in contact_lines:
        text = normalize_caption_text(line)
        font = _pick_font(text, brand, 40)
        _draw_line(draw, (0, y), text, font, _rgba("#FFFFFF", 0.88), anchor_centre_x=centre)
        y += int(sum(font.getmetrics()) * 1.3)

    ensure_parent(out_path)
    background.convert("RGB").save(out_path, "PNG")
    return {
        "path": out_path,
        "style": style,
        "has_logo": bool(brand.logo_path and Path(brand.logo_path).exists()),
        "contact_lines": len(contact_lines),
        "content_bottom": y,
        "fits": y < height - 80,
    }


# --------------------------------------------------------------------------
# FFmpeg composition
# --------------------------------------------------------------------------
@dataclass
class TimedOverlay:
    png: str
    start: float = 0.0
    end: Optional[float] = None
    x: str = "0"
    y: str = "0"
    fade: float = 0.18
    #: Per-edge override. ``None`` means "use ``fade``". Setting either to 0.0
    #: is what makes a run of word-level caption frames read as one steady
    #: card: only the first frame fades in and only the last fades out.
    fade_in: Optional[float] = None
    fade_out: Optional[float] = None

    def edge_fades(self) -> Tuple[float, float]:
        first = self.fade if self.fade_in is None else self.fade_in
        last = self.fade if self.fade_out is None else self.fade_out
        return max(first, 0.0), max(last, 0.0)


def build_overlay_graph(
    overlays: Sequence[TimedOverlay],
    *,
    base_label: str = "0:v",
    out_label: str = "vout",
    first_input_index: int = 1,
) -> Tuple[str, List[str]]:
    """Compose timed PNG overlays onto a base video stream.

    Returns the filtergraph fragment and the ``-i`` arguments for each overlay
    image, in matching order.
    """
    if not overlays:
        return f"[{base_label}]null[{out_label}]", []

    inputs: List[str] = []
    parts: List[str] = []
    current = base_label
    for offset, overlay in enumerate(overlays):
        index = first_input_index + offset
        inputs += ["-loop", "1", "-i", overlay.png]
        label_in = f"ov{offset}"
        chain = f"[{index}:v]format=rgba"
        fade_in, fade_out = overlay.edge_fades()
        if (fade_in > 0 or fade_out > 0) and overlay.end is not None:
            span = max(overlay.end - overlay.start, 0.3)
            fade_in = min(fade_in, span / 2)
            fade_out = min(fade_out, span / 2)
            if fade_in > 0:
                chain += f",fade=t=in:st={overlay.start:.2f}:d={fade_in:.2f}:alpha=1"
            if fade_out > 0:
                chain += (
                    f",fade=t=out:st={max(overlay.end - fade_out, overlay.start):.2f}"
                    f":d={fade_out:.2f}:alpha=1"
                )
        parts.append(f"{chain}[{label_in}]")
        enable = ""
        if overlay.end is not None:
            # Half-open, not `between`: `between` is inclusive at both ends, so
            # two abutting frames both draw on the boundary frame. With an
            # opaque card that is invisible; with a transparent one (the
            # stroke-only subtitle template) the boundary frame renders twice
            # as dense and the line pulses once per word.
            enable = (
                f":enable='gte(t,{overlay.start:.3f})*lt(t,{overlay.end:.3f})'"
            )
        elif overlay.start > 0:
            enable = f":enable='gte(t,{overlay.start:.3f})'"
        label_out = f"vc{offset}" if offset < len(overlays) - 1 else out_label
        parts.append(
            f"[{current}][{label_in}]overlay={overlay.x}:{overlay.y}"
            f":shortest=0:format=auto{enable}[{label_out}]"
        )
        current = label_out
    return ";".join(parts), inputs
