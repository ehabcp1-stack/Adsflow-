"""Arabic caption engine.

PRODUCT RULE: captions are drawn by AdFlow AI, never by a video model. A
generative model cannot be trusted with Arabic letterforms, and a caption that
renders reversed or disconnected destroys an otherwise good ad.

Why this file is more than "draw some text"
-------------------------------------------
Arabic needs *shaping* (each letter takes an initial/medial/final/isolated
form) and *bidi reordering* (right-to-left, with Latin and digits running
left-to-right inside it). Pillow does both correctly when it is built with
Raqm — but only if it is handed LOGICAL text and told ``direction="rtl"``.
Pre-shaping the string first (the common arabic-reshaper + python-bidi recipe)
double-reverses it under Raqm and produces mirrored Arabic. So:

* Raqm present  -> pass logical text, ``direction="rtl"``  (verified path)
* Raqm absent   -> fall back to arabic-reshaper + python-bidi

Second problem: most high-quality Arabic fonts carry no Latin glyphs, so
"TADAFQ" or a phone number inside an Arabic line renders as empty boxes. We
therefore lay the line out token by token — Arabic runs right-to-left in the
Arabic font, Latin/number runs left-to-right in the Latin font — which is
word-level bidi and is exactly what ad copy needs.

The result is a transparent full-frame PNG handed to FFmpeg as a timed
overlay: typography stays under our control and the output is testable.
"""
from __future__ import annotations

import functools
import hashlib
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont, features

from app.media.ffmpeg import OUT_HEIGHT, OUT_WIDTH

log = logging.getLogger("adflow.media.captions")

try:  # pragma: no cover - import guard
    import arabic_reshaper
    from bidi.algorithm import get_display

    LEGACY_SHAPING = True
except Exception:  # pragma: no cover
    arabic_reshaper = None  # type: ignore[assignment]
    get_display = None  # type: ignore[assignment]
    LEGACY_SHAPING = False


@functools.lru_cache(maxsize=1)
def raqm_available() -> bool:
    try:
        return bool(features.check("raqm"))
    except Exception:  # pragma: no cover
        return False


def shaping_ready() -> bool:
    return raqm_available() or LEGACY_SHAPING


# --------------------------------------------------------------------------
# Fonts
# --------------------------------------------------------------------------
#: Ordered fallbacks per named family. The first existing file wins. Installing
#: Cairo or Tajawal (the brand fonts) upgrades the look with no code change.
ARABIC_FONT_CANDIDATES: Dict[str, Sequence[str]] = {
    "cairo": (
        "/usr/share/fonts/truetype/adflow/Cairo-Bold.ttf",
        "/usr/share/fonts/truetype/google-fonts/Cairo-Bold.ttf",
        "/usr/share/fonts/truetype/cairo/Cairo-Bold.ttf",
    ),
    "tajawal": (
        "/usr/share/fonts/truetype/adflow/Tajawal-Bold.ttf",
        "/usr/share/fonts/truetype/google-fonts/Tajawal-Bold.ttf",
        "/usr/share/fonts/truetype/tajawal/Tajawal-Bold.ttf",
    ),
    "almarai": ("/usr/share/fonts/truetype/google-fonts/Almarai-Bold.ttf",),
    "noto kufi arabic": ("/usr/share/fonts/truetype/noto/NotoKufiArabic-Bold.ttf",),
    "noto naskh arabic": ("/usr/share/fonts/truetype/noto/NotoNaskhArabic-Bold.ttf",),
    "amiri": ("/usr/share/fonts/truetype/fonts-hosny-amiri/Amiri-Bold.ttf",),
}
#: Ordered by how a caption actually reads on a phone, not by how common the
#: font is. Cairo and Tajawal are the brand faces and win when the image ships
#: them. Failing that, **Kufi before Sans**: Noto Sans Arabic is a text face —
#: correct, but thin and quiet at caption size — while Noto Kufi is a display
#: face with the weight an ad caption needs over a photograph.
ARABIC_FONT_DEFAULTS: Sequence[str] = (
    "/usr/share/fonts/truetype/adflow/Cairo-Bold.ttf",
    "/usr/share/fonts/truetype/google-fonts/Cairo-Bold.ttf",
    "/usr/share/fonts/truetype/adflow/Tajawal-Bold.ttf",
    "/usr/share/fonts/truetype/google-fonts/Tajawal-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoKufiArabic-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)
LATIN_FONT_DEFAULTS: Sequence[str] = (
    "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
)


def _first_existing(paths: Sequence[str]) -> Optional[str]:
    for candidate in paths:
        if candidate and Path(candidate).exists():
            return candidate
    return None


@functools.lru_cache(maxsize=32)
def resolve_arabic_font(family: Optional[str] = None) -> Optional[str]:
    """Find a real font file able to draw Arabic. Never guesses a path."""
    named = ARABIC_FONT_CANDIDATES.get((family or "").strip().lower(), ())
    found = _first_existing(tuple(named) + tuple(ARABIC_FONT_DEFAULTS))
    if found:
        return found
    try:  # pragma: no cover - environment dependent
        out = subprocess.run(
            ["fc-match", "-f", "%{file}", ":lang=ar"], capture_output=True, text=True, timeout=10
        ).stdout.strip()
        if out and Path(out).exists():
            return out
    except Exception:
        pass
    return None


@functools.lru_cache(maxsize=32)
def resolve_latin_font(family: Optional[str] = None) -> Optional[str]:
    named = (f"/usr/share/fonts/truetype/google-fonts/{family}-Bold.ttf",) if family else ()
    return _first_existing(tuple(named) + tuple(LATIN_FONT_DEFAULTS))


@functools.lru_cache(maxsize=128)
def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


@functools.lru_cache(maxsize=32)
def font_charset(path: str) -> frozenset:
    """Every codepoint a font file can actually draw.

    A font that lacks a character does not fail — it draws .notdef, the empty
    box. One box in the middle of an ad caption is the kind of defect a viewer
    reads as "made by a machine", so coverage is checked rather than assumed.
    """
    try:
        from fontTools.ttLib import TTFont

        with TTFont(path, fontNumber=0, lazy=True) as font:
            codes: set = set()
            for table in font["cmap"].tables:
                codes |= set(table.cmap.keys())
        return frozenset(codes)
    except Exception:  # pragma: no cover - fontTools missing or odd font
        return frozenset()


def font_covers(path: Optional[str], text: str) -> bool:
    charset = font_charset(path) if path else frozenset()
    if not charset:
        return True  # unknown coverage: assume yes rather than reject a face
    return all(ord(ch) in charset or ch.isspace() for ch in text)


def arabic_font_for(text: str, family: Optional[str] = None) -> Optional[str]:
    """Pick the Arabic face that can draw THIS caption.

    Display faces are the right look for an ad but the thinnest coverage: Noto
    Kufi has no hyphen, colon or Latin percent. Rather than ship a box, the
    caption falls through to the next face that covers what it needs — and the
    heavier face is still used for every caption that does not need them.
    """
    named = ARABIC_FONT_CANDIDATES.get((family or "").strip().lower(), ())
    candidates = [p for p in tuple(named) + tuple(ARABIC_FONT_DEFAULTS) if Path(p).exists()]
    # Only what the Arabic face will actually be asked to draw. Latin words and
    # standalone punctuation go to the Latin face, so their coverage here is
    # irrelevant — judging the face on them would reject a good one over a
    # hyphen it is never handed.
    normalized = normalize_caption_text(text)
    arabic_part = "".join(
        token for token in normalized.split() if _token_script(token) == "arabic"
    )
    for path in candidates:
        if font_covers(path, arabic_part):
            return path
    return resolve_arabic_font(family)


# --------------------------------------------------------------------------
# Text normalisation and script runs
# --------------------------------------------------------------------------
ARABIC_RANGES = (
    (0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF), (0xFE70, 0xFEFF),
)

#: Characters Arabic display fonts frequently lack, mapped to safe equivalents
#: so a caption never shows an empty box.
PUNCTUATION_FALLBACK = str.maketrans({
    "—": "-", "–": "-", "‑": "-", "‒": "-",
    "…": "...", "•": "-", "·": "-", "%": "٪",
    "“": '"', "”": '"', "„": '"', "‘": "'", "’": "'",
    " ": " ", "‏": "", "‎": "", "‪": "", "‫": "", "‬": "",
})


def normalize_caption_text(text: str) -> str:
    return " ".join((text or "").translate(PUNCTUATION_FALLBACK).split())


def is_arabic_char(ch: str) -> bool:
    code = ord(ch)
    return any(lo <= code <= hi for lo, hi in ARABIC_RANGES)


def contains_arabic(text: str) -> bool:
    return any(is_arabic_char(ch) for ch in text or "")


def _token_script(token: str) -> str:
    """Classify a whitespace-delimited token by its first strong character."""
    for ch in token:
        if is_arabic_char(ch):
            return "arabic"
        if ch.isalpha() or ch.isdigit():
            # Arabic-Indic digits belong to the Arabic run so numbers stay put.
            return "arabic" if 0x0660 <= ord(ch) <= 0x0669 else "latin"
    # A token that is only punctuation — a dash opening a line, a lone colon.
    # Arabic display faces routinely lack these, so they go to the Latin face,
    # which has all of them, instead of inheriting an Arabic run and rendering
    # as an empty box.
    return "punct"


def shape_for_draw(text: str) -> Tuple[str, Dict[str, Any]]:
    """Return (string to draw, Pillow draw kwargs) for an Arabic run."""
    if raqm_available():
        return text, {"direction": "rtl", "language": "ar"}
    if LEGACY_SHAPING:  # pragma: no cover - only on builds without Raqm
        return get_display(arabic_reshaper.reshape(text)), {}
    raise RuntimeError(
        "Arabic shaping unavailable: Pillow needs Raqm, or install arabic-reshaper "
        "and python-bidi. AdFlow AI refuses to render broken Arabic."
    )


# --------------------------------------------------------------------------
# Style
# --------------------------------------------------------------------------
@dataclass
class CaptionStyle:
    template: str = "bold_bar"
    font_family: Optional[str] = None
    latin_font_family: Optional[str] = None
    font_size: int = 62
    text_color: str = "#FFFFFF"
    accent_color: str = "#FBBF24"
    box_color: str = "#000000"
    box_opacity: float = 0.72
    stroke_width: int = 4
    stroke_color: str = "#000000"
    line_spacing: float = 1.30
    position: str = "bottom"  # bottom | center | top
    #: Percentages of the frame that captions must never enter.
    safe_top_pct: float = 12.0
    safe_bottom_pct: float = 18.0
    safe_side_pct: float = 8.0
    max_lines: int = 3
    word_gap_px: int = 14

    def key(self) -> str:
        return hashlib.md5(repr(sorted(self.__dict__.items())).encode()).hexdigest()[:10]


CAPTION_TEMPLATES: List[Dict[str, Any]] = [
    {
        "key": "bold_bar",
        "label_en": "Bold Bar",
        "label_ar": "شريط عريض",
        "style": {"box_opacity": 0.74, "stroke_width": 2, "font_size": 62},
    },
    {
        "key": "clean_line",
        "label_en": "Clean Line",
        "label_ar": "سطر نظيف",
        "style": {"box_opacity": 0.0, "stroke_width": 6, "font_size": 60},
    },
    {
        "key": "word_highlight",
        "label_en": "Word Highlight",
        "label_ar": "تمييز كلمة",
        "style": {"box_opacity": 0.0, "stroke_width": 5, "font_size": 64},
    },
    {
        # The restrained broadcast look: a thin line low in frame that stays
        # out of the way of the photography. Developer brand films use this
        # rather than the heavy social bar — the picture is the pitch, and the
        # caption is there for a viewer watching with the sound off.
        "key": "subtitle",
        "label_en": "Subtitle",
        "label_ar": "سطر خفيف",
        "style": {
            "box_opacity": 0.0, "stroke_width": 3, "font_size": 44,
            "safe_bottom_pct": 9.0, "line_spacing": 1.2, "max_lines": 2,
        },
    },
]


def style_for_template(template: str, **overrides: Any) -> CaptionStyle:
    preset = next((t for t in CAPTION_TEMPLATES if t["key"] == template), CAPTION_TEMPLATES[0])
    values: Dict[str, Any] = {"template": preset["key"], **preset["style"]}
    values.update({k: v for k, v in overrides.items() if v is not None})
    known = set(CaptionStyle.__dataclass_fields__)  # type: ignore[attr-defined]
    return CaptionStyle(**{k: v for k, v in values.items() if k in known})


def _rgba(hex_color: str, opacity: float = 1.0) -> Tuple[int, int, int, int]:
    value = (hex_color or "#FFFFFF").lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    try:
        r, g, b = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    except (ValueError, IndexError):
        r, g, b = 255, 255, 255
    return (r, g, b, max(0, min(255, int(round(opacity * 255)))))


# --------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------
@dataclass
class _Run:
    text: str
    script: str
    width: float
    font: ImageFont.FreeTypeFont
    draw_text: str
    draw_kwargs: Dict[str, Any]
    highlight: bool = False


def _build_runs(tokens: Sequence[str], style: CaptionStyle,
                ar_font: ImageFont.FreeTypeFont, la_font: ImageFont.FreeTypeFont,
                measure: ImageDraw.ImageDraw, highlight: str = "",
                highlight_index: Optional[int] = None,
                index_offset: int = 0) -> List[_Run]:
    """Merge adjacent same-script tokens into runs and measure them.

    A highlighted word is kept as its own run so only that word takes the
    accent colour — merging it into the sentence would tint the whole line.

    `highlight_index` selects the word by position across the whole caption
    (`index_offset` is where this line starts in that sequence). Word-level
    captions need it: a line that says the same word twice would otherwise
    light both, and the highlight would appear to jump backwards.
    """
    runs: List[_Run] = []
    for position, token in enumerate(tokens):
        script = _token_script(token)
        if script == "punct":
            script = "latin"
        if highlight_index is not None:
            is_highlight = (index_offset + position) == highlight_index
        else:
            is_highlight = bool(highlight) and token.strip(".,،:;!؟") == highlight
        # Word-level captions draw one frame per word of the SAME line. Merging
        # neighbours into a run — and splitting whichever word is lit back out
        # of it — changes how many word gaps the line contains, so every word
        # after the highlight shifts a few pixels as the highlight travels. The
        # line reads as trembling. When a positional highlight is in play, every
        # token becomes its own run, so the layout is identical in all frames
        # and only the colour moves. (Arabic letters never join across a space,
        # so per-word shaping is the same shaping.)
        uniform = highlight_index is not None
        mergeable = (
            not uniform
            and runs and runs[-1].script == script
            and not is_highlight and not runs[-1].highlight
        )
        if mergeable:
            runs[-1].text = f"{runs[-1].text} {token}"
        else:
            runs.append(_Run(token, script, 0.0, ar_font, token, {}, is_highlight))
    for run in runs:
        if run.script == "arabic":
            run.font = ar_font
            run.draw_text, run.draw_kwargs = shape_for_draw(run.text)
        else:
            run.font = la_font
            run.draw_text, run.draw_kwargs = run.text, {}
        run.width = measure.textlength(run.draw_text, font=run.font, **run.draw_kwargs)
    return runs


def _line_width(runs: Sequence[_Run], gap: int) -> float:
    if not runs:
        return 0.0
    return sum(r.width for r in runs) + gap * (len(runs) - 1)


def measure_line(text: str, style: CaptionStyle, ar_font: ImageFont.FreeTypeFont,
                 la_font: ImageFont.FreeTypeFont, measure: ImageDraw.ImageDraw,
                 highlight: str = "") -> float:
    runs = _build_runs(text.split(), style, ar_font, la_font, measure, highlight)
    return _line_width(runs, style.word_gap_px)


def wrap_lines(text: str, style: CaptionStyle, max_width_px: int,
               ar_font: ImageFont.FreeTypeFont, la_font: ImageFont.FreeTypeFont,
               measure: ImageDraw.ImageDraw) -> List[str]:
    """Break on real word boundaries, measured in pixels, in logical order."""
    words = [w for w in normalize_caption_text(text).split() if w]
    if not words:
        return []
    def greedy(limit: float) -> List[str]:
        out: List[str] = []
        current: List[str] = []
        for word in words:
            candidate = current + [word]
            if not current or measure_line(" ".join(candidate), style, ar_font, la_font, measure) <= limit:
                current = candidate
            else:
                out.append(" ".join(current))
                current = [word]
        if current:
            out.append(" ".join(current))
        return out

    lines = greedy(max_width_px)
    # Balance: greedy wrapping strands a single word on the last line, which
    # reads as a mistake on a caption. Re-wrap at a narrower limit and keep the
    # result only if it uses the same number of lines.
    if len(lines) > 1:
        target = max_width_px
        for _ in range(6):
            target *= 0.92
            candidate = greedy(target)
            if len(candidate) != len(lines):
                break
            lines = candidate
    return lines[: style.max_lines]


# --------------------------------------------------------------------------
# Rasterisation
# --------------------------------------------------------------------------
def render_caption_png(
    text: str,
    out_path: str,
    *,
    style: Optional[CaptionStyle] = None,
    width: int = OUT_WIDTH,
    height: int = OUT_HEIGHT,
    highlight_word: Optional[str] = None,
    highlight_index: Optional[int] = None,
) -> Dict[str, Any]:
    """Draw one caption into a transparent full-frame PNG.

    Returns geometry so callers can assert the caption stayed inside the safe
    zone instead of trusting that it did.
    """
    style = style or CaptionStyle()
    # Picked per caption, not per install: the heaviest face wins unless this
    # particular line contains something it cannot draw.
    arabic_path = arabic_font_for(text, style.font_family)
    latin_path = resolve_latin_font(style.latin_font_family)
    if not arabic_path:
        raise RuntimeError("No Arabic-capable font found. Install fonts-noto-core.")
    ar_font = _font(arabic_path, style.font_size)
    la_font = _font(latin_path or arabic_path, style.font_size)

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    side_margin = int(width * style.safe_side_pct / 100.0)
    max_text_width = width - 2 * side_margin - 48
    lines = wrap_lines(text, style, max_text_width, ar_font, la_font, draw)
    if not lines:
        raise ValueError("caption text is empty")

    ascent, descent = ar_font.getmetrics()
    line_height = int((ascent + descent) * style.line_spacing)
    block_height = line_height * len(lines)

    safe_top = int(height * style.safe_top_pct / 100.0)
    safe_bottom = height - int(height * style.safe_bottom_pct / 100.0)
    if style.position == "top":
        block_top = safe_top
    elif style.position == "center":
        block_top = (height - block_height) // 2
    else:
        block_top = safe_bottom - block_height
    block_top = max(safe_top, min(block_top, max(safe_bottom - block_height, safe_top)))

    highlight = (highlight_word or "").strip()
    line_runs = []
    consumed = 0
    for line in lines:
        tokens = line.split()
        line_runs.append(
            _build_runs(tokens, style, ar_font, la_font, draw, highlight,
                        highlight_index=highlight_index, index_offset=consumed)
        )
        consumed += len(tokens)
    line_widths = [_line_width(runs, style.word_gap_px) for runs in line_runs]

    # The background box is sized from the layout WITHOUT any highlight.
    # Highlighting splits a token into its own run, which adds a word gap and
    # changes the measured width by a few pixels — invisible in one frame, but
    # word-level captions draw one frame per word, so the box would breathe in
    # and out as the highlight travelled along the line.
    plain_widths = [
        _line_width(_build_runs(line.split(), style, ar_font, la_font, draw), style.word_gap_px)
        for line in lines
    ]
    block_width = int(max(plain_widths + line_widths)) if line_widths else 0

    if style.box_opacity > 0:
        pad_x, pad_y = 34, 22
        draw.rounded_rectangle(
            [
                max(side_margin - 8, (width - block_width) / 2 - pad_x),
                block_top - pad_y,
                min(width - side_margin + 8, (width + block_width) / 2 + pad_x),
                block_top + block_height + pad_y,
            ],
            radius=22,
            fill=_rgba(style.box_color, style.box_opacity),
        )

    base_is_rtl = contains_arabic(" ".join(lines))

    for index, runs in enumerate(line_runs):
        y = block_top + index * line_height
        line_w = line_widths[index]
        start_x = (width - line_w) / 2
        # Base direction decides which end the first run occupies.
        ordered = list(reversed(runs)) if base_is_rtl else runs
        x = start_x
        for run in ordered:
            fill = style.accent_color if run.highlight else style.text_color
            draw.text(
                (x, y), run.draw_text, font=run.font, fill=_rgba(fill),
                stroke_width=style.stroke_width,
                stroke_fill=_rgba(style.stroke_color, 0.85) if style.stroke_width else None,
                **run.draw_kwargs,
            )
            x += run.width + style.word_gap_px

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path, "PNG", optimize=True)
    return {
        "path": out_path,
        "lines": lines,
        "line_count": len(lines),
        "arabic_font": arabic_path,
        "latin_font": latin_path,
        "font_size": style.font_size,
        "block_top": block_top,
        "block_bottom": block_top + block_height,
        "block_width": block_width,
        "safe_top": safe_top,
        "safe_bottom": safe_bottom,
        "within_safe_zone": block_top >= safe_top and block_top + block_height <= safe_bottom,
        "rtl": base_is_rtl,
        "engine": "raqm" if raqm_available() else "reshaper+bidi",
    }


#: Below this a highlight is a flicker rather than emphasis, so the word is
#: folded into its neighbour's frame instead of getting one of its own.
MIN_KARAOKE_WORD_SEC = 0.14


def expand_word_level(captions: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Turn cues carrying word timings into per-word highlight frames.

    The card text never changes within a cue — only which word is lit. That is
    what makes the caption feel spoken rather than pasted: the viewer's eye is
    pulled along the line at the pace of the voice, and the line itself stays
    still.

    A cue without word timings passes through untouched, so a project with no
    voice-over still gets ordinary captions.
    """
    out: List[Dict[str, Any]] = []
    for caption in captions:
        words = caption.get("words") or []
        if len(words) < 2:
            out.append({k: v for k, v in caption.items() if k != "words"})
            continue

        cue_start = float(caption.get("start", 0.0))
        cue_end = float(caption.get("end", 0.0))
        frames: List[Dict[str, Any]] = []
        for position, word in enumerate(words):
            start = max(float(word.get("start", cue_start)), cue_start)
            end = min(float(word.get("end", cue_end)), cue_end)
            if end - start < MIN_KARAOKE_WORD_SEC and frames:
                # Too short to read — extend the previous highlight over it
                # rather than flashing a frame nobody can perceive.
                frames[-1]["end"] = end
                continue
            frames.append({
                **{k: v for k, v in caption.items() if k != "words"},
                "start": start,
                "end": end,
                "highlight_word": word.get("word"),
                # Repeated words in one line would otherwise all light up.
                "highlight_index": position,
            })
        if not frames:
            out.append({k: v for k, v in caption.items() if k != "words"})
            continue
        # Cover the whole cue: the first frame starts with it and the last ends
        # with it, so there is never a gap where the card disappears.
        frames[0]["start"] = cue_start
        frames[-1]["end"] = cue_end
        # The renderer needs to know which frames are the edges of the cue.
        # Everything in between is the *same card* with the highlight moved,
        # so fading those in and out makes the line pulse once per word — the
        # flicker is the fade, not the typography.
        for frame in frames:
            frame["cue_first"] = False
            frame["cue_last"] = False
        frames[0]["cue_first"] = True
        frames[-1]["cue_last"] = True
        out.extend(frames)
    return out


def render_caption_track(
    captions: Sequence[Dict[str, Any]],
    out_dir: str,
    *,
    style: Optional[CaptionStyle] = None,
    width: int = OUT_WIDTH,
    height: int = OUT_HEIGHT,
) -> List[Dict[str, Any]]:
    """Rasterise a whole caption track. Each entry gains ``png`` + geometry."""
    style = style or CaptionStyle()
    captions = expand_word_level(captions)
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    rendered: List[Dict[str, Any]] = []
    for index, caption in enumerate(captions):
        text = normalize_caption_text(caption.get("text") or "")
        if not text:
            continue
        png = directory / f"caption_{index:03d}_{style.key()}.png"
        geometry = render_caption_png(
            text, str(png), style=style, width=width, height=height,
            highlight_word=caption.get("highlight_word"),
            highlight_index=caption.get("highlight_index"),
        )
        rendered.append({**caption, "png": str(png),
                         "geometry": {k: v for k, v in geometry.items() if k != "path"}})
    return rendered
