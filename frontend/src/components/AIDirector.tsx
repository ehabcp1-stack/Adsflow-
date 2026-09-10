'use client';

import clsx from 'clsx';
import { Sparkles } from 'lucide-react';

import { useLocale } from '@/i18n/LocaleProvider';
import type { DirectorNote } from '@/lib/types';

import { Badge, Button } from './ui';

/**
 * Reusable AI Director recommendation surface. Appears across the workflow;
 * recommendations stay short and actionable.
 */
export function AIDirector({
  notes,
  onAction,
  compact = false,
  className,
}: {
  notes?: DirectorNote[] | null;
  onAction?: (note: DirectorNote) => void;
  compact?: boolean;
  className?: string;
}) {
  const { t, locale } = useLocale();
  if (!notes || notes.length === 0) return null;

  return (
    <section
      className={clsx(
        'rounded-2xl border border-accent/20 bg-gradient-to-b from-accent-soft/70 to-surface p-4',
        className,
      )}
    >
      <div className="mb-3 flex items-center gap-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent text-white">
          <Sparkles className="h-3.5 w-3.5" />
        </span>
        <span className="text-[13px] font-semibold text-accent-dark">{t.director.title}</span>
      </div>

      <ul className={clsx('space-y-2.5', compact && 'space-y-2')}>
        {notes.slice(0, compact ? 2 : 4).map((note) => (
          <li key={note.key} className="flex items-start justify-between gap-3">
            <p className="text-[13.5px] leading-relaxed text-ink-soft">
              {locale === 'ar' ? note.message_ar : note.message_en}
            </p>
            <div className="flex shrink-0 items-center gap-2">
              <Badge tone={note.impact === 'high' ? 'accent' : 'neutral'}>
                {note.impact === 'high'
                  ? t.director.impactHigh
                  : note.impact === 'medium'
                    ? t.director.impactMedium
                    : t.director.impactLow}
              </Badge>
              {note.action && onAction ? (
                <Button size="sm" variant="secondary" onClick={() => onAction(note)}>
                  {t.common.approve}
                </Button>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Single-line director hint used inside dense panels. */
export function DirectorHint({ ar, en }: { ar: string; en: string }) {
  const { locale } = useLocale();
  return (
    <p className="flex items-start gap-2 rounded-xl bg-accent-soft/60 px-3 py-2 text-[12.5px] text-accent-dark">
      <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      {locale === 'ar' ? ar : en}
    </p>
  );
}
