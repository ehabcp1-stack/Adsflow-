'use client';

import { Check, Languages, Wand2 } from 'lucide-react';
import { useState } from 'react';

import { Badge, Button, Card, CardTitle, InlineError } from '@/components/ui';
import { useLocale } from '@/i18n/LocaleProvider';
import type { ApiError } from '@/lib/api';
import { applyAll, applyFlag, replaceEverywhere, type ScriptEdit } from '@/lib/dialect';
import type { DialectFlag, ScriptLine } from '@/lib/types';

/**
 * Dialect check — the user's own hand on the script.
 *
 * The generator drifted into Gulf Arabic: "النص يستخدم الخليجي أكثر من
 * العراقي". Three things now push back on that — the writing rules the model
 * receives, a `gulf_free` dimension in the QA score, and this panel. The first
 * two are the system's opinion; this one is his, and it is the one that
 * decides, because he is the person who knows how people talk where the ad
 * runs. So every suggestion here is editable before it is taken, and the box
 * at the bottom replaces a word no dictionary knows about.
 *
 * Nothing is written until he saves: a swap per version would bury the real
 * history under thirty versions of one line.
 */
export function DialectCheck({
  lines,
  flags,
  dirty,
  saving,
  saveError,
  onChange,
  onSave,
}: {
  lines: ScriptLine[];
  flags: DialectFlag[];
  dirty: boolean;
  saving: boolean;
  saveError: ApiError | null;
  onChange: (edit: ScriptEdit) => void;
  onSave: () => void;
}) {
  const { t, locale, num } = useLocale();
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [word, setWord] = useState('');
  const [instead, setInstead] = useState('');

  const keyOf = (flag: DialectFlag) => `${flag.line_index}:${flag.start}:${flag.found}`;
  const kindLabel = (kind: DialectFlag['kind']) =>
    kind === 'gulf' ? t.script.gulf : kind === 'msa' ? t.script.msa : t.script.forbidden;

  const replace = (flag: DialectFlag) => {
    const chosen = drafts[keyOf(flag)] ?? flag.suggest;
    onChange(applyFlag(lines, flags, flag, chosen.trim()));
  };

  const custom = () => {
    if (!word.trim()) return;
    onChange(replaceEverywhere(lines, flags, word, instead.trim()));
    setWord('');
    setInstead('');
  };

  return (
    <Card>
      <CardTitle
        action={
          flags.length > 0 ? (
            <Badge tone="warn">
              <span className="ltr-nums">{num(flags.length)}</span>
            </Badge>
          ) : (
            <Badge tone="ok">
              <Check className="h-3.5 w-3.5" />
            </Badge>
          )
        }
      >
        <span className="inline-flex items-center gap-2">
          <Languages className="h-4 w-4 text-accent" />
          {t.script.dialectCheck}
        </span>
      </CardTitle>

      {flags.length === 0 ? (
        <p className="text-[12.5px] text-ink-muted">{t.script.dialectClean}</p>
      ) : (
        <>
          <p className="mb-3 text-[12.5px] text-ink-muted">{t.script.dialectHint}</p>

          <ul className="space-y-2.5">
            {flags.map((flag) => {
              const key = keyOf(flag);
              const line = lines[flag.line_index];
              const draft = drafts[key] ?? flag.suggest;
              const deleting = !draft.trim();
              return (
                <li key={key} className="rounded-xl border border-warn/25 bg-warn/[0.06] p-3">
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-[14px] font-semibold text-ink">{flag.found}</span>
                    <Badge tone={flag.kind === 'forbidden' ? 'danger' : 'warn'}>
                      {kindLabel(flag.kind)}
                    </Badge>
                  </div>

                  {/* Where it sits, so a word that is fine in this sentence and
                      wrong in another can be judged on the sentence. */}
                  {line ? (
                    <p className="mt-1 line-clamp-2 text-[12px] text-ink-faint">
                      {line.voice_line.slice(Math.max(0, flag.start - 28), flag.start)}
                      <mark className="rounded bg-warn/25 px-0.5 text-ink">{flag.found}</mark>
                      {line.voice_line.slice(flag.end, flag.end + 28)}
                    </p>
                  ) : null}

                  <p className="mt-1.5 text-[12px] text-ink-muted">
                    {locale === 'ar' ? flag.reason_ar : flag.reason_en}
                  </p>

                  <div className="mt-2 flex items-center gap-2">
                    <input
                      className="field h-9 flex-1 py-1 text-[13.5px]"
                      value={draft}
                      placeholder={t.script.customReplacement}
                      onChange={(event) =>
                        setDrafts((current) => ({ ...current, [key]: event.target.value }))
                      }
                    />
                    <Button size="sm" variant="secondary" onClick={() => replace(flag)}>
                      {deleting ? t.script.remove : t.script.replace}
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>

          <Button
            size="sm"
            variant="secondary"
            className="mt-3"
            icon={<Wand2 className="h-3.5 w-3.5" />}
            onClick={() => onChange(applyAll(lines, flags))}
          >
            {t.script.replaceAll}
          </Button>
        </>
      )}

      {/* The dictionary is deliberately conservative — it only holds words that
          are clearly not Iraqi — so it will never cover every word he wants
          gone. This is the part that does not depend on us knowing the word. */}
      <div className="mt-4 space-y-2 border-t border-line pt-3">
        <div className="flex items-center gap-2">
          <input
            className="field h-9 flex-1 py-1 text-[13.5px]"
            placeholder={t.script.customWord}
            value={word}
            onChange={(event) => setWord(event.target.value)}
          />
          <input
            className="field h-9 flex-1 py-1 text-[13.5px]"
            placeholder={t.script.customReplacement}
            value={instead}
            onChange={(event) => setInstead(event.target.value)}
          />
        </div>
        <Button size="sm" variant="ghost" disabled={!word.trim()} onClick={custom}>
          {t.script.customApply}
        </Button>
      </div>

      {dirty ? (
        <div className="mt-3 flex items-center justify-between gap-2 rounded-xl bg-accent-soft px-3 py-2">
          <span className="text-[12.5px] font-medium text-accent-dark">{t.script.unsaved}</span>
          <Button size="sm" loading={saving} onClick={onSave}>
            {t.common.save}
          </Button>
        </div>
      ) : null}

      <InlineError error={saveError} />
    </Card>
  );
}
