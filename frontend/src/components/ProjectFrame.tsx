'use client';

import { useParams } from 'next/navigation';

import { useApi } from '@/lib/hooks';
import type { ProjectDetail } from '@/lib/types';

import { BudgetBar, ProjectHeader, ProjectStepper } from './ProjectShell';
import { Card, ErrorState, LoadingBlock } from './ui';

/**
 * Shared frame for every stage screen: project header, visual progress flow
 * and the always-visible budget guard.
 */
export function ProjectFrame({
  children,
  actions,
  sidebar,
  pollMs,
}: {
  children: (project: ProjectDetail, reload: () => void) => React.ReactNode;
  actions?: (project: ProjectDetail, reload: () => void) => React.ReactNode;
  sidebar?: (project: ProjectDetail, reload: () => void) => React.ReactNode;
  pollMs?: number;
}) {
  const params = useParams<{ id: string }>();
  const id = params?.id;
  const { data: project, error, loading, reload } = useApi<ProjectDetail>(id ? `/projects/${id}` : null, { pollMs });

  if (error && !project) return <ErrorState error={error} onRetry={reload} />;
  if (loading && !project) {
    return (
      <Card>
        <LoadingBlock lines={6} />
      </Card>
    );
  }
  if (!project) return null;

  const refresh = () => void reload(true);

  return (
    <>
      <ProjectHeader project={project} actions={actions?.(project, refresh)} />
      <ProjectStepper project={project} />
      <div className={sidebar ? 'grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]' : ''}>
        <div className="min-w-0">{children(project, refresh)}</div>
        {sidebar ? (
          <aside className="space-y-4">
            <BudgetBar budget={project.budget} />
            {sidebar(project, refresh)}
          </aside>
        ) : null}
      </div>
    </>
  );
}

export function useProjectId(): string {
  const params = useParams<{ id: string }>();
  return params?.id ?? '';
}
