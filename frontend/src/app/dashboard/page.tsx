'use client';

import { ArrowLeft, ArrowRight, Clapperboard, Plus, Wand2 } from 'lucide-react';
import Link from 'next/link';

import { PageHeader } from '@/components/AppShell';
import { ProjectCard } from '@/components/ProjectCard';
import { Button, Card, EmptyState, ErrorState, LoadingBlock, Skeleton, Stat } from '@/components/ui';
import { useLocale } from '@/i18n/LocaleProvider';
import { useApi } from '@/lib/hooks';
import type { ProjectSummary } from '@/lib/types';

type DashboardData = {
  brand: { product: string; parent: string };
  metrics: {
    monthly_ai_spend_usd: number;
    monthly_target_usd: number;
    completed_videos: number;
    active_projects: number;
  };
  recent_projects: ProjectSummary[];
};

export default function DashboardPage() {
  const { t, money, num, isRTL } = useLocale();
  const { data, error, loading, reload } = useApi<DashboardData>('/dashboard');
  const Arrow = isRTL ? ArrowLeft : ArrowRight;

  return (
    <>
      <PageHeader
        title={t.dashboard.title}
        subtitle={t.dashboard.subtitle}
        actions={
          <Link href="/projects/new">
            <Button icon={<Plus className="h-4 w-4" />}>{t.dashboard.createNew}</Button>
          </Link>
        }
      />

      {error ? <ErrorState error={error} onRetry={reload} /> : null}

      {/* Primary actions */}
      <div className="mb-6 grid gap-4 md:grid-cols-2">
        <Link href="/projects/new" className="card card-hover group flex items-start gap-4 p-5">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-accent text-white">
            <Wand2 className="h-5 w-5" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-2 text-[16px] font-semibold text-ink">
              {t.dashboard.createNew}
              <Arrow className="h-4 w-4 text-ink-faint transition group-hover:translate-x-0.5 rtl:group-hover:-translate-x-0.5" />
            </span>
            <span className="mt-1 block text-[13px] text-ink-muted">{t.dashboard.createNewHint}</span>
          </span>
        </Link>

        <Link href="/projects/new?mode=video_remix_reel" className="card card-hover group flex items-start gap-4 p-5">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-ink text-white">
            <Clapperboard className="h-5 w-5" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-2 text-[16px] font-semibold text-ink">
              {t.dashboard.remix}
              <Arrow className="h-4 w-4 text-ink-faint transition group-hover:translate-x-0.5 rtl:group-hover:-translate-x-0.5" />
            </span>
            <span className="mt-1 block text-[13px] text-ink-muted">{t.dashboard.remixHint}</span>
          </span>
        </Link>
      </div>

      {/* Minimal metrics */}
      <div className="mb-8 grid gap-4 sm:grid-cols-3">
        {loading && !data ? (
          <>
            <Skeleton className="h-[92px]" />
            <Skeleton className="h-[92px]" />
            <Skeleton className="h-[92px]" />
          </>
        ) : (
          <>
            <Stat
              label={t.dashboard.monthlySpend}
              value={money(data?.metrics.monthly_ai_spend_usd ?? 0)}
              sub={`${money(data?.metrics.monthly_target_usd ?? 0)} ${t.dashboard.ofTarget}`}
              tone="accent"
            />
            <Stat label={t.dashboard.completed} value={num(data?.metrics.completed_videos ?? 0)} tone="ok" />
            <Stat label={t.dashboard.activeProjects} value={num(data?.metrics.active_projects ?? 0)} />
          </>
        )}
      </div>

      {/* Recent projects */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-[16px] font-semibold text-ink">{t.dashboard.recent}</h2>
          <Link href="/projects" className="text-[13px] font-medium text-accent hover:underline">
            {t.common.all}
          </Link>
        </div>

        {loading && !data ? (
          <Card>
            <LoadingBlock lines={4} />
          </Card>
        ) : data && data.recent_projects.length > 0 ? (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {data.recent_projects.map((project) => (
              <ProjectCard key={project.id} project={project} />
            ))}
          </div>
        ) : (
          <EmptyState
            title={t.dashboard.noProjects}
            action={
              <Link href="/projects/new">
                <Button icon={<Plus className="h-4 w-4" />}>{t.dashboard.createNew}</Button>
              </Link>
            }
          />
        )}
      </section>
    </>
  );
}
