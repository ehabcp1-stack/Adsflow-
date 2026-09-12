"""Word timing for the voice-over.

Captions that drift are the single most obvious "made by a machine" tell in a
vertical ad — a viewer forgives a soft image, never a caption that lands after
the word. So captions are timed against the voice track that actually exists,
not against the plan that produced it.

Two sources of truth, in order:

1. **The provider's own alignment.** Some TTS vendors return per-character or
   per-word timings with the audio. When one does, that is ground truth and
   nothing here second-guesses it.
2. **Estimated alignment.** Otherwise timings are derived from the *measured*
   duration of the rendered audio and a per-word weight. This is honest
   estimation, not measurement, and every timing it produces is labelled
   `source="estimated"` so no screen can claim precision it does not have.

The weighting is Arabic-aware. Arabic script is an abjad: short vowels are
usually unwritten, so character count understates spoken length, and the
shortfall is not uniform — a word of four consonants takes noticeably longer
to say than four Latin characters take to read. Long vowels (ا و ي), the
shadda (which doubles a consonant) and the tie-less ta marbuta all change
duration, and the definite article "ال" is spoken as part of the following
word rather than as its own beat.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

#: Characters that carry extra spoken length in Arabic.
_LONG_VOWELS = set("اآأإوىيﻯ")
_SHADDA = "ّ"
_TASHKEEL = "".join(chr(c) for c in range(0x064B, 0x0653))

#: A pause is added after these, because a reader does pause there.
_PAUSE_AFTER = {".": 0.28, "،": 0.18, ",": 0.18, "؟": 0.30, "?": 0.30,
                "!": 0.26, ":": 0.16, "؛": 0.20, "…": 0.32}

#: Floor and ceiling for one word, so a weighting bug cannot produce a caption
#: that flashes for 40ms or sits for four seconds.
MIN_WORD_SEC = 0.12
MAX_WORD_SEC = 1.60


@dataclass(frozen=True)
class WordTiming:
    word: str
    start: float
    end: float
    #: "provider" when the vendor supplied it, "estimated" when we derived it.
    source: str = "estimated"

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 3)

    def as_dict(self) -> Dict[str, Any]:
        return {"word": self.word, "start": round(self.start, 3),
                "end": round(self.end, 3), "source": self.source}


@dataclass
class CaptionCue:
    """One caption card: the words on screen and when they are on screen."""

    text: str
    start: float
    end: float
    words: List[WordTiming] = field(default_factory=list)
    source: str = "estimated"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "words": [w.as_dict() for w in self.words],
            "source": self.source,
        }


def _strip_tashkeel(word: str) -> str:
    return "".join(c for c in word if c not in _TASHKEEL)


def word_weight(word: str) -> float:
    """Roughly how long this word takes to say, in arbitrary units.

    Calibrated so that a typical Iraqi ad sentence lands within a few percent
    of its measured duration; absolute scale does not matter because the
    weights are normalised against the real audio length.
    """
    bare = _strip_tashkeel(word)
    core = re.sub(r"[^\w؀-ۿ]", "", bare)
    if not core:
        return 0.0

    # The definite article is spoken as part of the word it attaches to, not
    # as two separate beats.
    if core.startswith("ال") and len(core) > 3:
        core = core[1:]

    weight = 0.0
    for char in core:
        if char in _LONG_VOWELS:
            weight += 1.35          # long vowels are held
        elif unicodedata.category(char) == "Nd":
            weight += 2.20          # digits are spoken as whole number words
        elif "؀" <= char <= "ۿ":
            weight += 1.20          # unwritten short vowels ride along
        else:
            weight += 1.0
    weight += word.count(_SHADDA) * 0.9   # a doubled consonant is held
    return weight


def pause_after(word: str) -> float:
    for mark, seconds in _PAUSE_AFTER.items():
        if word.rstrip().endswith(mark):
            return seconds
    return 0.0


def _from_provider(payload: Sequence[Dict[str, Any]], offset: float) -> List[WordTiming]:
    out: List[WordTiming] = []
    for item in payload:
        word = str(item.get("word") or item.get("text") or "").strip()
        if not word:
            continue
        start = float(item.get("start", item.get("start_time", 0.0))) + offset
        end = float(item.get("end", item.get("end_time", start))) + offset
        if end <= start:
            end = start + MIN_WORD_SEC
        out.append(WordTiming(word=word, start=start, end=end, source="provider"))
    return out


def align_words(
    text: str,
    duration_sec: float,
    *,
    provider_alignment: Optional[Sequence[Dict[str, Any]]] = None,
    offset_sec: float = 0.0,
) -> List[WordTiming]:
    """Time every word of `text` across `duration_sec` of real audio.

    `duration_sec` must be the *measured* length of the rendered audio, not the
    length the script hoped for — that difference is exactly the drift this
    module exists to remove.
    """
    if provider_alignment:
        timed = _from_provider(provider_alignment, offset_sec)
        if timed:
            return timed

    words = [w for w in re.split(r"\s+", (text or "").strip()) if w]
    if not words or duration_sec <= 0:
        return []

    weights = [word_weight(w) for w in words]
    pauses = [pause_after(w) for w in words]
    # The last pause is trailing silence, not a gap between words.
    pauses[-1] = 0.0
    speakable = max(duration_sec - sum(pauses), duration_sec * 0.55)
    total_weight = sum(weights) or float(len(words))

    timings: List[WordTiming] = []
    cursor = offset_sec
    for word, weight, pause in zip(words, weights, pauses):
        span = speakable * (weight / total_weight)
        span = max(MIN_WORD_SEC, min(span, MAX_WORD_SEC))
        timings.append(WordTiming(word=word, start=cursor, end=cursor + span))
        cursor += span + pause

    produced = cursor - offset_sec
    if produced <= 0 or abs(produced - duration_sec) <= 0.05:
        return timings

    if produced > duration_sec:
        # The words do not fit: genuinely compress them.
        scale = duration_sec / produced
        return [
            WordTiming(
                word=t.word,
                start=offset_sec + (t.start - offset_sec) * scale,
                end=offset_sec + (t.end - offset_sec) * scale,
                source=t.source,
            )
            for t in timings
        ]

    # The audio is longer than the words warrant — a held breath, a musical
    # beat, a slow read. That surplus is SILENCE, not word length: stretching
    # each word to fill it would leave a caption sitting on one word for
    # seconds. So the extra time goes into the gaps between words, and each
    # word keeps the duration it takes to say.
    slack = duration_sec - produced
    share = slack / len(timings)
    spread: List[WordTiming] = []
    shift = 0.0
    for timing in timings:
        spread.append(WordTiming(word=timing.word, start=timing.start + shift,
                                 end=timing.end + shift, source=timing.source))
        shift += share
    # The last word still has to close on the audio, so it holds the remainder.
    last = spread[-1]
    spread[-1] = WordTiming(word=last.word, start=last.start,
                            end=max(last.end, offset_sec + duration_sec), source=last.source)
    return spread


def group_into_cues(
    words: Iterable[WordTiming],
    *,
    max_chars: int = 32,
    max_duration_sec: float = 2.6,
    min_duration_sec: float = 0.7,
) -> List[CaptionCue]:
    """Group timed words into caption cards.

    A cue breaks on a sentence-ending mark, on length, or on time — whichever
    comes first. Vertical video gives a caption about two short lines before it
    starts competing with the picture, which is what `max_chars` encodes.
    """
    cues: List[CaptionCue] = []
    current: List[WordTiming] = []

    def flush() -> None:
        if not current:
            return
        text = " ".join(w.word for w in current)
        start, end = current[0].start, current[-1].end
        if end - start < min_duration_sec:
            end = start + min_duration_sec
        source = "provider" if all(w.source == "provider" for w in current) else "estimated"
        cues.append(CaptionCue(text=text, start=start, end=end, words=list(current), source=source))
        current.clear()

    for word in words:
        current.append(word)
        text_len = sum(len(w.word) + 1 for w in current) - 1
        span = current[-1].end - current[0].start
        # Break on any real punctuation pause, not only a full stop: a caption
        # that runs across a comma reads as one breath when it was two.
        ends_sentence = pause_after(word.word) >= 0.18
        if ends_sentence or text_len >= max_chars or span >= max_duration_sec:
            flush()
    flush()

    # Never let one cue overlap the next — two captions on screen at once reads
    # as a bug even when each is individually correct.
    for earlier, later in zip(cues, cues[1:]):
        if earlier.end > later.start:
            earlier.end = max(later.start - 0.02, earlier.start + min_duration_sec * 0.5)
    return cues


def retime_segments(
    segments: Sequence[Dict[str, Any]], measured_duration_sec: float
) -> List[Dict[str, Any]]:
    """Stretch planned segment boundaries onto the voice that was produced.

    The storyboard plans scene lengths from an estimate. Once the voice exists
    its real length is known, and the scenes have to follow the voice rather
    than the other way round — a scene that ends mid-sentence is the artefact
    this removes.
    """
    planned = max((float(s.get("end", 0.0)) for s in segments), default=0.0)
    if planned <= 0 or measured_duration_sec <= 0:
        return [dict(s) for s in segments]
    scale = measured_duration_sec / planned
    out: List[Dict[str, Any]] = []
    for segment in segments:
        moved = dict(segment)
        moved["start"] = round(float(segment.get("start", 0.0)) * scale, 3)
        moved["end"] = round(float(segment.get("end", 0.0)) * scale, 3)
        out.append(moved)
    return out
