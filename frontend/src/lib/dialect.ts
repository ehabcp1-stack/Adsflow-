import type { DialectFlag, ScriptLine } from './types';

/**
 * Editing a script by the dialect flags the backend measured.
 *
 * Every function here works from the `start`/`end` offsets that came with the
 * flag. None of them searches the text for the flagged word again: matching an
 * Arabic word boundary needs a lookbehind (`(?<![\w؀-ۿ])`) that
 * Safari only shipped in 16.4, and a second implementation of that rule would
 * be free to drift from `services/dialect.py`, which is the one that decided
 * the word was wrong in the first place. Offsets cannot drift.
 *
 * The one exception is `replaceEverywhere`, where the user types the word
 * himself — see the note there.
 */
export type ScriptEdit = { lines: ScriptLine[]; flags: DialectFlag[] };

function sameFlag(a: DialectFlag, b: DialectFlag): boolean {
  return a.line_index === b.line_index && a.start === b.start && a.found === b.found;
}

/**
 * Swap one flagged word for `replacement`, and move every flag that sits after
 * it in the same line by the same number of characters. Without that shift the
 * second swap in a line lands on the wrong characters — the panel would cut a
 * word in half and look, from the outside, like the dictionary was wrong.
 *
 * An empty `replacement` is a deletion (some Gulf courtesies have no Iraqi
 * equivalent), and it takes one neighbouring space with it so the line does
 * not keep a double space where the word used to be.
 */
export function applyFlag(
  lines: ScriptLine[],
  flags: DialectFlag[],
  target: DialectFlag,
  replacement: string,
): ScriptEdit {
  const line = lines[target.line_index];
  if (!line) return { lines, flags };

  const text = line.voice_line;
  let start = target.start;
  let end = target.end;
  if (!replacement) {
    if (text[end] === ' ') end += 1;
    else if (text[start - 1] === ' ') start -= 1;
  }

  const edited = text.slice(0, start) + replacement + text.slice(end);
  const delta = start + replacement.length - end;

  return {
    lines: lines.map((item, index) =>
      index === target.line_index ? { ...item, voice_line: edited } : item,
    ),
    flags: flags
      .filter((flag) => !sameFlag(flag, target))
      .map((flag) =>
        flag.line_index === target.line_index && flag.start >= end
          ? { ...flag, start: flag.start + delta, end: flag.end + delta }
          : flag,
      ),
  };
}

/**
 * Take every suggestion at once, back to front.
 *
 * Applying them in reverse order means each replacement only ever moves
 * characters that have already been dealt with, so no offset in the queue can
 * go stale mid-loop.
 */
export function applyAll(lines: ScriptLine[], flags: DialectFlag[]): ScriptEdit {
  const ordered = [...flags].sort(
    (a, b) => b.line_index - a.line_index || b.start - a.start,
  );
  let state: ScriptEdit = { lines, flags };
  for (const flag of ordered) {
    state = applyFlag(state.lines, state.flags, flag, flag.suggest);
  }
  return state;
}

/**
 * Replace a word the user typed himself, everywhere it appears.
 *
 * This is the half of the feature the dictionary cannot cover: he knows words
 * that read wrong in his city and are in no list. Because he typed the word,
 * a plain substring replacement is exactly what he asked for — no boundary
 * rule to disagree about. The flags on any line this touches are dropped
 * rather than guessed at; saving brings back a freshly measured set.
 */
export function replaceEverywhere(
  lines: ScriptLine[],
  flags: DialectFlag[],
  word: string,
  replacement: string,
): ScriptEdit {
  const needle = word.trim();
  if (!needle) return { lines, flags };

  const touched = new Set<number>();
  const nextLines = lines.map((line, index) => {
    if (!line.voice_line.includes(needle)) return line;
    touched.add(index);
    const edited = line.voice_line.split(needle).join(replacement).replace(/\s{2,}/g, ' ').trim();
    return { ...line, voice_line: edited };
  });

  return { lines: nextLines, flags: flags.filter((flag) => !touched.has(flag.line_index)) };
}

/**
 * A line split into plain runs and flagged runs, so the script itself can show
 * which words are in question — the user asked to fix "any word I see that is
 * not Iraqi", and seeing it is the first half of that.
 */
export function segmentsFor(
  text: string,
  flags: DialectFlag[],
): { text: string; flag: DialectFlag | null }[] {
  const ordered = [...flags].sort((a, b) => a.start - b.start);
  const out: { text: string; flag: DialectFlag | null }[] = [];
  let cursor = 0;

  for (const flag of ordered) {
    if (flag.start < cursor || flag.end > text.length) continue;
    if (flag.start > cursor) out.push({ text: text.slice(cursor, flag.start), flag: null });
    out.push({ text: text.slice(flag.start, flag.end), flag });
    cursor = flag.end;
  }
  if (cursor < text.length) out.push({ text: text.slice(cursor), flag: null });
  return out;
}
