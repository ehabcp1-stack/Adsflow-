'use client';

import { Plus } from 'lucide-react';
import Link from 'next/link';
import { useMemo, useState } from 'react';

import { PageHeader } from '@/components/AppShell';
import { ProjectCard } from '@/components/ProjectCard';
import { Button, EmptyState, ErrorState, Skeleton, Tabs } from '@/components/ui';
import { useLocale } from '@/i18n/LocaleProvider';
import { useApi } from '@/lib/hooks';
import type { ProjectSummary } from '@/lib/types';

type Filter = 'all' | 'active' | 'done';

export default function ProjectsPage() {
  const { t } = useLocale();
  const [filter, setFilter] = useState<Filter>('all');
  const { data, error, loading, reload } = useApi<{ items: ProjectSummary[]; total: number }>('/projects');

  const items = useMemo(() => {
    const all = data?.items ?? [];
    if (filter === 'active') return all.filter((p) => p.state !== 'EXPORTED' && p.state !== 'CANCELLED');
    if (filter === 'done') return all.filter((p) => p.state === 'EXPORTED');
    return all;
  }, [data, filter]);

  return (
    <>
      <PageHeader
        title={t.nav.projects}
        subtitle={t.dashboard.subtitle}
        actions={
          <Link href="/projects/new">
            <Button icon={<Plus className="h-4 w-4" />}>{t.dashboard.createNew}</Button>
          </Link>
        }
      />

      <div className="mb-5 max-w-md">
        <Tabs<Filter>
          value={filter}
          onChange={setFilter}
          tabs={[
            { value: 'all', label: t.common.all, count: data?.items.length },
            {
              value: 'active',
              label: t.dashboard.activeProjects,
              count: data?.items.filter((p) => p.state !== 'EXPORTED' && p.state !== 'CANCELLED').length,
            },
            {
              value: 'done',
              label: t.dashboard.completed,
              count: data?.items.filter((p) => p.state === 'EXPORTED').length,
            },
          ]}
        />
      </div>

      {error ? <ErrorState error={error} onRetry={reload} /> : null}

      {loading && !data ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((index) => (
            <Skeleton key={index} className="h-[260px]" />
          ))}
        </div>
      ) : items.length > 0 ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {items.map((project) => (
            <ProjectCard key={project.id} project={project} />
          ))}
        </div>
      ) : (
        !error && (
          <EmptyState
            title={t.dashboard.noProjects}
            action={
              <Link href="/projects/new">
                <Button icon={<Plus className="h-4 w-4" />}>{t.dashboard.createNew}</Button>
              </Link>
            }
          />
        )
      )}
    </>
  );
}
