'use client';

/**
 * Project cost dashboard — reads `GET /projects/{id}/costs` (budget snapshot +
 * breakdown + the real cost ledger). Deliberately reads like a studio panel,
 * not an accounting screen: five numbers, two derived rates, one provider
 * breakdown. Every figure comes from the ledger; nothing is invented.
 *
 * Money always renders LTR via `.ltr-nums` (CLAUDE.md §8).
 */
import clsx from 'clsx';
import { Receipt } from 'lucide-react';
import { useMemo } from 'react';

import { useLocale } from '@/i18n/LocaleProvider';
import { useApi } from '@/lib/hooks';
import type { ProjectCosts } from '@/lib/types';

import { Badge, Card, CardTitle, ErrorState, LoadingBlock, Progress } from './ui';

function aggregate(costs: ProjectCosts) {
  const byProvider = new Map<string, { total: number; entries: number; mock: boolean }>();
  for (const entry of costs.ledger) {
    const value = entry.actual_cost_usd || entry.estimated_cost_usd;
    const current = byProvider.get(entry.provider) ?? { total: 0, entries: 0, mock: true };
    byProvider.set(entry.provider, {
      total: Math.round((current.total + value) * 10000) / 10000,
      entries: current.entries + 1,
      mock: current.mock && entry.is_mock,
    });
  }
  return [...byProvider.entries()]
    .map(([provider, value]) => ({ provider, ...value }))
    .sort((a, b) => b.total - a.total || a.provider.localeCompare(b.provider));
}

export function CostPanel({
  projectId,
  sceneCount,
  compact = false,
}: {
  projectId: string;
  /** Scene count from the storyboard/plan when the caller has it. */
  sceneCount?: number;
  compact?: boolean;
}) {
  const { t, money, num } = useLocale();
  const { data, error, loading, reload } = useApi<ProjectCosts>(`/projects/${projectId}/costs`);

  const providers = useMemo(() => (data ? aggregate(data) : []), [data]);

  if (loading && !data) {
    return (
      <Card>
        <LoadingBlock lines={compact ? 3 : 5} />
      </Card>
    );
  }
  if (error && !data) {
    return (
      <Card>
        <CardTitle>{t.costs.title}</CardTitle>
        <ErrorState error={error} onRetry={reload} />
      </Card>
    );
  }
  if (!data) return null;

  const spent = data.actual_cost_usd;
  const committed = spent + data.reserved_cost_usd;
  const used = data.budget_limit_usd > 0 ? (committed / data.budget_limit_usd) * 100 : 0;
  const tone = data.over_budget || used > 90 ? 'danger' : used > 70 ? 'warn' : 'ok';

  // Cost per scene comes from ledger rows that carry a scene id; fall back to
  // the caller's scene count so the average is over real scenes, not rows.
  const scenes = sceneCount ?? Object.keys(data.by_scene).length;
  const perScene = scenes > 0 ? committed / scenes : 0;
  // One project produces one finished reel, so its full committed cost is the
  // cost of that reel.
  const perReel = committed;
  const allMock = data.ledger.length > 0 && data.ledger.every((entry) => entry.is_mock);

  return (
    <Card>
      <CardTitle
        action={
          <Badge tone={data.over_budget ? 'warn' : 'ok'}>
            {data.over_budget ? t.costs.approvalRequired : t.costs.safe}
          </Badge>
        }
      >
        {t.costs.title}
      </CardTitle>

      {/* Compact mode sits under the persistent BudgetBar, which already draws
          the budget gauge — don't repeat it. */}
      {!compact ? (
        <>
          <p className="-mt-2 mb-4 text-[13px] text-ink-muted">{t.costs.subtitle}</p>
          <div className="mb-4">
            <div className="mb-1.5 flex flex-wrap items-baseline justify-between gap-2">
              <span className="ltr-nums text-[22px] font-semibold leading-none text-ink">{money(committed)}</span>
              <span className="ltr-nums text-[12.5px] text-ink-muted">
                {t.costs.budget}: {money(data.budget_limit_usd)}
              </span>
            </div>
            <Progress value={used} tone={tone} />
          </div>
        </>
      ) : null}

      <dl
        className={clsx(
          'grid gap-x-4 gap-y-2.5 text-[13px]',
          compact ? 'grid-cols-2' : 'grid-cols-2 sm:grid-cols-3',
        )}
      >
        {/* In full mode the budget is the headline above; in compact mode the
            panel has to carry it itself. */}
        {compact ? <Figure label={t.costs.budget} value={money(data.budget_limit_usd)} /> : null}
        <Figure label={t.costs.estimated} value={money(data.estimated_cost_usd)} />
        <Figure label={t.costs.actual} value={money(spent)} strong />
        <Figure label={t.costs.reserved} value={money(data.reserved_cost_usd)} />
        <Figure
          label={t.costs.remaining}
          value={money(data.remaining_budget_usd)}
          tone={data.remaining_budget_usd <= 0 ? 'warn' : 'ok'}
        />
        <Figure
          label={t.costs.perScene}
          value={scenes > 0 ? money(perScene) : '—'}
          hint={scenes > 0 ? `${t.costs.perSceneHint} · ${num(scenes)}` : undefined}
        />
        <Figure label={t.costs.perReel} value={money(perReel)} hint={t.costs.perReelHint} />
      </dl>

      <div className="mt-4 border-t border-line pt-4">
        <div className="mb-2 flex items-center justify-between">
          <p className="section-title">{t.costs.byProvider}</p>
          <span className="ltr-nums text-[11.5px] text-ink-faint">
            {num(data.ledger.length)} {t.costs.entries}
          </span>
        </div>

        {providers.length === 0 ? (
          <div className="flex items-start gap-2.5 rounded-xl border border-dashed border-line bg-raised px-3.5 py-3">
            <Receipt className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
            <span>
              <span className="block text-[13px] font-medium text-ink">{t.costs.empty}</span>
              <span className="block text-[12px] text-ink-muted">{t.costs.emptyHint}</span>
            </span>
          </div>
        ) : (
          <ul className="space-y-1.5">
            {providers.map((row) => {
              const share = committed > 0 ? (row.total / committed) * 100 : 0;
              return (
                <li key={row.provider} className="flex items-center gap-3 text-[13px]">
                  <span className="w-24 shrink-0 truncate text-ink-soft">{row.provider}</span>
                  <Progress value={share} tone={row.mock ? 'accent' : 'ok'} className="flex-1" />
                  <span className="ltr-nums w-16 shrink-0 text-end font-medium text-ink-soft">
                    {money(row.total)}
                  </span>
                </li>
              );
            })}
          </ul>
        )}

        {allMock ? <p className="mt-2.5 text-[12px] text-ink-faint">{t.costs.mockZero}</p> : null}
      </div>

      {!compact && Object.keys(data.by_operation).length > 0 ? (
        <div className="mt-4 border-t border-line pt-4">
          <p className="section-title mb-2">{t.costs.byOperation}</p>
          <ul className="grid gap-x-5 gap-y-1.5 text-[12.5px] sm:grid-cols-2">
            {Object.entries(data.by_operation)
              .sort((a, b) => b[1] - a[1])
              .map(([operation, value]) => (
                <li key={operation} className="flex items-center justify-between">
                  <span className="truncate text-ink-muted">{operation.replace(/_/g, ' ')}</span>
                  <span className="ltr-nums ps-2 font-medium text-ink-soft">{money(value)}</span>
                </li>
              ))}
          </ul>
        </div>
      ) : null}
    </Card>
  );
}

function Figure({
  label,
  value,
  hint,
  strong,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  strong?: boolean;
  tone?: 'ok' | 'warn';
}) {
  return (
    <div>
      <dt className="text-[11.5px] text-ink-faint">{label}</dt>
      <dd
        className={clsx(
          'ltr-nums font-semibold',
          strong ? 'text-[16px]' : 'text-[14px]',
          tone === 'warn' ? 'text-warn' : tone === 'ok' ? 'text-ok' : 'text-ink',
        )}
      >
        {value}
      </dd>
      {hint ? <p className="text-[11px] text-ink-faint">{hint}</p> : null}
    </div>
  );
}
