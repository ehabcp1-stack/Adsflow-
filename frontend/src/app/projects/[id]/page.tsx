'use client';

import { ArrowLeft, ArrowRight, Copy, PlayCircle } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';

import { CostPanel } from '@/components/CostPanel';
import { ProjectFrame } from '@/components/ProjectFrame';
import { AssetUploader } from '@/components/AssetUploader';
import { Badge, Button, Card, CardTitle, Field, InlineError } from '@/components/ui';
import { useLocale } from '@/i18n/LocaleProvider';
import { api } from '@/lib/api';
import { useApi, useMutation } from '@/lib/hooks';
import type { Asset, ProjectDetail } from '@/lib/types';

export default function ProjectBriefPage() {
  const { t, isRTL } = useLocale();
  const router = useRouter();
  const Next = isRTL ? ArrowLeft : ArrowRight;
  const [edited, setEdited] = useState<Partial<ProjectDetail>>({});

  return (
    <ProjectFrame
      actions={(project) => (
        <>
          <Link href={`/projects/${project.id}/analysis`}>
            <Button icon={<PlayCircle className="h-4 w-4" />}>{t.analysis.run}</Button>
          </Link>
        </>
      )}
      sidebar={(project) => <ProjectSidebar project={project} />}
    >
      {(project, reload) => (
        <BriefEditor project={project} reload={reload} edited={edited} setEdited={setEdited} onNext={() => router.push(`/projects/${project.id}/analysis`)} NextIcon={Next} />
      )}
    </ProjectFrame>
  );
}

function BriefEditor({
  project,
  reload,
  edited,
  setEdited,
  onNext,
  NextIcon,
}: {
  project: ProjectDetail;
  reload: () => void;
  edited: Partial<ProjectDetail>;
  setEdited: (value: Partial<ProjectDetail>) => void;
  onNext: () => void;
  NextIcon: React.ComponentType<{ className?: string }>;
}) {
  const { t } = useLocale();
  const { data: assetData, reload: reloadAssets } = useApi<{ items: Asset[] }>(`/assets?project_id=${project.id}`);
  const value = <K extends keyof ProjectDetail>(key: K): ProjectDetail[K] =>
    (edited[key] !== undefined ? (edited[key] as ProjectDetail[K]) : project[key]);

  const save = useMutation(async () => {
    await api.patch(`/projects/${project.id}`, edited);
    setEdited({});
    reload();
  });

  const dirty = Object.keys(edited).length > 0;

  return (
    <div className="space-y-5">
      <Card>
        <CardTitle
          action={
            dirty ? (
              <Button size="sm" loading={save.pending} onClick={() => void save.run()}>
                {save.pending ? t.common.saving : t.common.save}
              </Button>
            ) : null
          }
        >
          {t.stages.brief}
        </CardTitle>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t.wizard.name}>
            <input
              className="field"
              value={String(value('name'))}
              onChange={(event) => setEdited({ ...edited, name: event.target.value })}
            />
          </Field>
          <Field label={t.wizard.cta}>
            <input
              className="field"
              value={String(value('cta'))}
              onChange={(event) => setEdited({ ...edited, cta: event.target.value })}
            />
          </Field>
          <Field label={t.wizard.targetAudience}>
            <input
              className="field"
              value={String(value('target_audience'))}
              onChange={(event) => setEdited({ ...edited, target_audience: event.target.value })}
            />
          </Field>
          <Field label={t.wizard.durationLabel}>
            <input
              type="number"
              className="field ltr-nums"
              value={Number(value('duration_sec'))}
              onChange={(event) => setEdited({ ...edited, duration_sec: Number(event.target.value) })}
            />
          </Field>
        </div>

        <div className="mt-4">
          <Field label={t.wizard.keyInformation}>
            <textarea
              className="field min-h-[130px] resize-y"
              value={String(value('key_information'))}
              onChange={(event) => setEdited({ ...edited, key_information: event.target.value })}
            />
          </Field>
        </div>

        <InlineError error={save.error} />

        <div className="mt-4 flex flex-wrap gap-2 border-t border-line pt-4">
          <Badge tone="neutral">{project.goal}</Badge>
          <Badge tone="neutral">{project.platform.replace(/_/g, ' ')}</Badge>
          <Badge tone="neutral">{project.language.replace(/_/g, ' ')}</Badge>
          <Badge tone="neutral">{project.dialect.replace(/_/g, ' ')}</Badge>
          <Badge tone="accent">{project.production_mode.replace(/_/g, ' ')}</Badge>
          <Badge tone="neutral">{project.quality_level.replace(/_/g, ' ')}</Badge>
        </div>
      </Card>

      <Card>
        <CardTitle>{t.wizard.assets}</CardTitle>
        {assetData && assetData.items.length === 0 ? (
          <p className="mb-3 text-[13px] text-ink-muted">{t.errors.noAssets}</p>
        ) : null}
        <div className="grid gap-4 sm:grid-cols-2">
          <AssetUploader
            projectId={project.id}
            kind="image"
            label={t.wizard.uploadImages}
            assets={(assetData?.items ?? []).filter((asset) => asset.kind === 'image')}
            onUploaded={() => reloadAssets()}
          />
          <AssetUploader
            projectId={project.id}
            kind="video"
            label={t.wizard.uploadVideos}
            assets={(assetData?.items ?? []).filter((asset) => asset.kind === 'video')}
            onUploaded={() => reloadAssets()}
          />
        </div>
      </Card>

      <div className="flex justify-end">
        <Button size="lg" icon={<NextIcon className="h-4 w-4" />} onClick={onNext}>
          {t.analysis.run}
        </Button>
      </div>
    </div>
  );
}

function ProjectSidebar({ project }: { project: ProjectDetail }) {
  const { t, date, num } = useLocale();
  const router = useRouter();
  const duplicate = useMutation(async () => {
    const clone = await api.post<ProjectDetail>(`/projects/${project.id}/duplicate`);
    router.push(`/projects/${clone.id}`);
    return clone;
  });

  const approvals = Object.entries(project.approvals).filter(([, info]) => info.status === 'approved');

  return (
    <>
      <CostPanel projectId={project.id} compact />

      <Card>
        <CardTitle>{t.common.approved}</CardTitle>
        {approvals.length === 0 ? (
          <p className="text-[13px] text-ink-muted">{t.common.empty}</p>
        ) : (
          <ul className="space-y-1.5">
            {approvals.map(([entity, info]) => (
              <li key={entity} className="flex items-center justify-between text-[13px]">
                <span className="text-ink-soft">{entity.replace(/_/g, ' ')}</span>
                <span className="ltr-nums text-ink-faint">
                  v{num(info.version)} · {date(info.approved_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card>
        <CardTitle>{t.export.archive}</CardTitle>
        <div className="space-y-2">
          <Button variant="secondary" full size="sm" icon={<Copy className="h-3.5 w-3.5" />} loading={duplicate.pending} onClick={() => void duplicate.run()}>
            {t.export.duplicate}
          </Button>
          <Link href={`/projects/${project.id}/export`} className="block">
            <Button variant="ghost" full size="sm">
              {t.export.title}
            </Button>
          </Link>
        </div>
      </Card>
    </>
  );
}
