'use client';

import { Clock, Film } from 'lucide-react';
import Link from 'next/link';

import { useLocale } from '@/i18n/LocaleProvider';
import { mediaUrl } from '@/lib/api';
import type { ProjectSummary } from '@/lib/types';

import { StateBadge } from './ProjectShell';

export function ProjectCard({ project }: { project: ProjectSummary }) {
  const { t, money, num, date } = useLocale();
  const thumb = mediaUrl(project.thumbnail_url);

  return (
    <Link href={`/projects/${project.id}`} className="card card-hover group block overflow-hidden p-0">
      <div className="relative aspect-[16/10] overflow-hidden bg-graphite-900">
        {thumb ? (
          <img
            src={thumb}
            alt={project.name}
            className="h-full w-full object-cover transition duration-500 group-hover:scale-[1.03]"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-slate-600">
            <Film className="h-7 w-7" />
          </div>
        )}
        <div className="absolute inset-x-0 bottom-0 flex items-center justify-between bg-gradient-to-t from-black/70 to-transparent p-3">
          <StateBadge state={project.state} />
          <span className="ltr-nums rounded-full bg-black/45 px-2 py-0.5 text-[11px] font-semibold text-white">
            {num(project.duration_sec)}s
          </span>
        </div>
      </div>

      <div className="p-4">
        <h3 className="truncate text-[15px] font-semibold text-ink">{project.name}</h3>
        <p className="mt-0.5 truncate text-[12.5px] text-ink-muted">
          {project.category.replace(/_/g, ' ')} · {project.goal} · {t.stages[project.stage]}
        </p>
        <div className="mt-3 flex items-center justify-between text-[12px] text-ink-faint">
          <span className="ltr-nums font-medium text-ink-soft">
            {project.actual_cost_usd > 0 ? money(project.actual_cost_usd) : money(project.estimated_cost_usd)}
            <span className="ms-1 text-ink-faint">
              {project.actual_cost_usd > 0 ? t.common.actual : t.common.estimated}
            </span>
          </span>
          <span className="flex items-center gap-1">
            <Clock className="h-3 w-3" />
            {date(project.updated_at)}
          </span>
        </div>
      </div>
    </Link>
  );
}
