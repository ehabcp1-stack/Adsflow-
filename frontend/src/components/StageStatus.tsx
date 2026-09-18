'use client';

import { AlertTriangle, Loader2 } from 'lucide-react';

import { useLocale } from '@/i18n/LocaleProvider';
import type { StageJob } from '@/lib/hooks';

/**
 * What a background writing stage is doing, said out loud.
 *
 * Analysis, concepts, script and storyboard run as jobs (see
 * `services/stage_jobs.py`). A job that dies in a worker is invisible unless
 * the screen says so — the version before this one left the user watching a
 * spinner over an analysis that had already failed and been lost. So: while
 * it works, say it is working and that leaving the page is safe; when it
 * fails, say what failed and offer the retry.
 */
export function StageStatus({
  job,
  working,
  onRetry,
}: {
  job: StageJob | null;
  working: boolean;
  onRetry: () => void;
}) {
  const { t, locale } = useLocale();
  // The backend sends English in `error_message` for logs and the API, and
  // Arabic alongside it only for failures the product itself produced. The
  // first version shipped both languages inside one string separated by a
  // slash; it rendered as a paragraph of mixed RTL and LTR — technically both
  // translations, practically neither.
  const reason = (locale === 'ar' && job?.error_ar) || job?.error_message || null;

  if (job?.status === 'failed') {
    return (
      <div className="mt-3 flex items-start gap-2 rounded-xl border border-danger/25 bg-danger/10 px-3 py-2.5 text-[13px] text-danger">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <div className="space-y-1">
          <p className="font-medium">{t.common.jobFailed}</p>
          {reason ? <p className="text-ink-soft">{reason}</p> : null}
          <button type="button" className="underline" onClick={onRetry}>
            {t.common.retry}
          </button>
        </div>
      </div>
    );
  }

  if (!working) return null;

  return (
    <p className="mt-3 flex items-center gap-2 text-[12.5px] text-ink-faint">
      <Loader2 className="h-3.5 w-3.5 animate-spin" />
      {job?.progress_label ? <span className="text-ink-muted">{job.progress_label}</span> : null}
      {t.common.inBackground}
    </p>
  );
}
