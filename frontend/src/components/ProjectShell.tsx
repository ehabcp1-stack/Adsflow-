'use client';

import clsx from 'clsx';
import { Check, Lock } from 'lucide-react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { useLocale } from '@/i18n/LocaleProvider';
import type { BudgetSnapshot, ProjectDetail, ProjectState, StageKey } from '@/lib/types';

import { Badge, Progress } from './ui';

export const STAGES: { key: StageKey; href: (id: string) => string }[] = [
  { key: 'brief', href: (id) => `/projects/${id}` },
  { key: 'analyze', href: (id) => `/projects/${id}/analysis` },
  { key: 'concepts', href: (id) => `/projects/${id}/concepts` },
  { key: 'script', href: (id) => `/projects/${id}/script` },
  { key: 'voice', href: (id) => `/projects/${id}/voice` },
  { key: 'storyboard', href: (id) => `/projects/${id}/storyboard` },
  { key: 'production', href: (id) => `/projects/${id}/production` },
  { key: 'edit', href: (id) => `/projects/${id}/edit` },
  { key: 'qc', href: (id) => `/projects/${id}/qc` },
  { key: 'export', href: (id) => `/projects/${id}/export` },
];

const STATE_TONE: Record<string, 'neutral' | 'accent' | 'ok' | 'warn' | 'danger'> = {
  DRAFT: 'neutral',
  ANALYZING: 'accent',
  ANALYSIS_READY: 'accent',
  CONCEPT_REVIEW: 'accent',
  CONCEPT_APPROVED: 'ok',
  SCRIPT_REVIEW: 'accent',
  SCRIPT_APPROVED: 'ok',
  STORYBOARD_REVIEW: 'accent',
  STORYBOARD_APPROVED: 'ok',
  PRODUCTION_READY: 'ok',
  GENERATING: 'warn',
  EDITING: 'accent',
  QC_REVIEW: 'warn',
  FINAL_APPROVAL: 'ok',
  EXPORTED: 'ok',
  PAUSED: 'neutral',
  FAILED: 'danger',
  CANCELLED: 'danger',
};

const STATE_LABEL_AR: Record<string, string> = {
  DRAFT: 'مسودة',
  ANALYZING: 'يحلل',
  ANALYSIS_READY: 'التحليل جاهز',
  CONCEPT_REVIEW: 'مراجعة الأفكار',
  CONCEPT_APPROVED: 'الفكرة معتمدة',
  SCRIPT_REVIEW: 'مراجعة النص',
  SCRIPT_APPROVED: 'النص معتمد',
  STORYBOARD_REVIEW: 'مراجعة الستوري بورد',
  STORYBOARD_APPROVED: 'الستوري بورد معتمد',
  PRODUCTION_READY: 'جاهز للإنتاج',
  GENERATING: 'قيد التوليد',
  EDITING: 'مونتاج',
  QC_REVIEW: 'فحص الجودة',
  FINAL_APPROVAL: 'اعتماد نهائي',
  EXPORTED: 'تم التصدير',
  PAUSED: 'موقوف',
  FAILED: 'فشل',
  CANCELLED: 'ملغى',
};

export function StateBadge({ state }: { state: ProjectState | string }) {
  const { locale } = useLocale();
  return (
    <Badge tone={STATE_TONE[state] ?? 'neutral'}>
      {locale === 'ar' ? STATE_LABEL_AR[state] ?? state : state.replace(/_/g, ' ').toLowerCase()}
    </Badge>
  );
}

/** Visual progress flow inside a project — the user always knows where they are. */
export function ProjectStepper({ project }: { project: ProjectDetail }) {
  const { t } = useLocale();
  const pathname = usePathname();
  const currentIndex = STAGES.findIndex((stage) => stage.key === project.stage);

  return (
    <div className="mb-5 overflow-x-auto">
      <ol className="flex min-w-max items-center gap-1.5">
        {STAGES.map((stage, index) => {
          const href = stage.href(project.id);
          const active = pathname === href;
          const done = index < currentIndex;
          return (
            <li key={stage.key} className="flex items-center">
              <Link
                href={href}
                className={clsx(
                  'flex items-center gap-2 rounded-xl px-3 py-2 text-[13px] font-medium transition',
                  active && 'bg-ink text-white shadow-card',
                  !active && done && 'bg-ok/10 text-ok hover:bg-ok/15',
                  !active && !done && 'text-ink-muted hover:bg-canvas',
                )}
              >
                <span
                  className={clsx(
                    'ltr-nums flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-semibold',
                    active ? 'bg-white/20 text-white' : done ? 'bg-ok/20 text-ok' : 'bg-line text-ink-faint',
                  )}
                >
                  {done ? <Check className="h-3 w-3" /> : index + 1}
                </span>
                {t.stages[stage.key]}
              </Link>
              {index < STAGES.length - 1 ? <span className="mx-0.5 h-px w-3 bg-line" /> : null}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/** Persistent budget guard bar — cost is always visible before spending. */
export function BudgetBar({ budget }: { budget: BudgetSnapshot }) {
  const { t, money } = useLocale();
  const used = budget.actual_cost_usd + budget.reserved_cost_usd;
  const pct = budget.budget_limit_usd > 0 ? (used / budget.budget_limit_usd) * 100 : 0;
  const tone = pct > 90 ? 'danger' : pct > 70 ? 'warn' : 'ok';
  return (
    <div className="card p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <span className="text-[13px] font-medium text-ink-soft">{t.common.budget}</span>
        <span className="ltr-nums text-[13px] text-ink-muted">
          {money(used)} / {money(budget.budget_limit_usd)}
        </span>
      </div>
      <Progress value={pct} tone={tone} />
      <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[12px] text-ink-faint">
        <span className="ltr-nums">
          {t.common.estimated}: {money(budget.estimated_cost_usd)}
        </span>
        <span className="ltr-nums">
          {t.common.actual}: {money(budget.actual_cost_usd)}
        </span>
        <span className="ltr-nums">
          {t.common.remaining}: {money(budget.remaining_budget_usd)}
        </span>
      </div>
    </div>
  );
}

/** Approval gate notice shown when a stage is blocked. */
export function GateNotice({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2.5 rounded-2xl border border-line bg-raised px-4 py-3 text-[13px] text-ink-soft">
      <Lock className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
      {message}
    </div>
  );
}

export function ProjectHeader({
  project,
  actions,
}: {
  project: ProjectDetail;
  actions?: React.ReactNode;
}) {
  const { t, num } = useLocale();
  return (
    <header className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div>
        <div className="mb-1.5 flex flex-wrap items-center gap-2">
          <StateBadge state={project.state} />
          <Badge tone="neutral">
            <span className="ltr-nums">{num(project.duration_sec)}s</span> · {project.platform.replace(/_/g, ' ')}
          </Badge>
          {project.voice_locked ? <Badge tone="ok">{t.voice.voiceLocked}</Badge> : null}
        </div>
        <h1 className="text-[24px] font-semibold tracking-tight text-ink sm:text-[28px]">{project.name}</h1>
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}
