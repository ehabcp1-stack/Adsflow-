'use client';

import { Copy, Download, FileVideo, Package, Sparkles } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import { ProjectFrame } from '@/components/ProjectFrame';
import {
  Badge,
  Button,
  Card,
  CardTitle,
  EmptyState,
  ErrorState,
  InlineError,
  LoadingBlock,
} from '@/components/ui';
import { useLocale } from '@/i18n/LocaleProvider';
import { api, mediaUrl } from '@/lib/api';
import { useApi, useMutation } from '@/lib/hooks';
import type { ExportItem, ProjectDetail, Render } from '@/lib/types';

type ExportPayload = {
  variants: { key: string; label_en: string; label_ar: string }[];
  ratios: string[];
  items: ExportItem[];
  render: Render | null;
  qc: { total_score: number; verdict: string; ready: boolean } | null;
  state: string;
};

export default function ExportPage() {
  return <ProjectFrame>{(project, reload) => <ExportView project={project} reloadProject={reload} />}</ProjectFrame>;
}

function ExportView({ project, reloadProject }: { project: ProjectDetail; reloadProject: () => void }) {
  const { t, locale, num, date } = useLocale();
  const router = useRouter();
  const { data, error, loading, reload } = useApi<ExportPayload>(`/projects/${project.id}/export`);
  const { data: archive } = useApi<any>(`/projects/${project.id}/archive`);

  const createExport = useMutation(async (variant: string, force = false) => {
    await api.post(`/projects/${project.id}/export`, { variant, aspect_ratio: '9:16', force });
    reload();
    reloadProject();
  });

  /**
   * Two distinct actions on the same endpoint:
   *   newVersion=true  → "new reel from this project" (a fresh cut, named as a
   *                      new version of the same campaign)
   *   newVersion=false → a plain duplicate to branch from
   */
  const duplicate = useMutation(async (newVersion: boolean) => {
    const clone = await api.post<ProjectDetail>(
      `/projects/${project.id}/duplicate${newVersion ? '?new_version=true' : ''}`,
    );
    router.push(`/projects/${clone.id}`);
  });

  if (loading && !data) return <LoadingBlock lines={6} />;
  if (!data) return <ErrorState error={error} onRetry={reload} />;

  const blocked = createExport.error?.code === 'qc_failed';

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
      <div className="space-y-5">
        <Card>
          <CardTitle
            action={
              data.qc ? (
                <Badge tone={data.qc.ready ? 'ok' : 'warn'}>
                  <span className="ltr-nums">{num(Math.round(data.qc.total_score))}</span>/100
                </Badge>
              ) : null
            }
          >
            {t.export.title}
          </CardTitle>

          <div className="grid gap-4 sm:grid-cols-[180px_minmax(0,1fr)]">
            <div className="overflow-hidden rounded-xl border border-line bg-graphite-900">
              {data.render?.url && data.render.url.endsWith('.mp4') ? (
                <video src={mediaUrl(data.render.url)} poster={mediaUrl(data.render.poster_url)} controls className="aspect-[9/16] w-full object-cover" />
              ) : data.render?.poster_url ? (
                <img src={mediaUrl(data.render.poster_url)} alt="" className="aspect-[9/16] w-full object-cover" />
              ) : (
                <div className="flex aspect-[9/16] w-full items-center justify-center text-slate-600">
                  <FileVideo className="h-7 w-7" />
                </div>
              )}
            </div>

            <div>
              <p className="ltr-nums text-[13px] text-ink-muted">
                {data.render ? `${data.render.width} × ${data.render.height}` : '1080 × 1920'} · 9:16 · MP4 · H.264
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                {data.variants.map((variant) => (
                  <Button
                    key={variant.key}
                    size="sm"
                    variant={variant.key === 'master' ? 'primary' : 'secondary'}
                    loading={createExport.pending}
                    /* Nothing to export until the reel has been assembled. */
                    disabled={!data.render}
                    title={!data.render ? t.edit.empty : undefined}
                    onClick={() => void createExport.run(variant.key)}
                  >
                    {locale === 'ar' ? variant.label_ar : variant.label_en}
                  </Button>
                ))}
              </div>
              {!data.render ? (
                <p className="mt-2 text-[12.5px] text-ink-muted">{t.edit.empty}</p>
              ) : null}

              <InlineError error={createExport.error} />
              {blocked ? (
                <Button
                  size="sm"
                  variant="danger"
                  className="mt-3"
                  loading={createExport.pending}
                  onClick={() => void createExport.run('master', true)}
                >
                  {t.export.exportAnyway}
                </Button>
              ) : null}
            </div>
          </div>
        </Card>

        <Card>
          <CardTitle>{t.export.files}</CardTitle>
          {data.items.length === 0 ? (
            <EmptyState title={t.export.empty} />
          ) : (
            <ul className="divide-y divide-line">
              {data.items.map((item) => (
                <li key={item.id} className="flex items-center justify-between gap-3 py-3">
                  <span className="flex min-w-0 items-center gap-3">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-canvas text-ink-soft">
                      <FileVideo className="h-4 w-4" />
                    </span>
                    <span className="min-w-0">
                      <span className="ltr-nums block truncate text-[13px] font-medium text-ink">{item.filename}</span>
                      <span className="ltr-nums block text-[11.5px] text-ink-faint">
                        {item.variant} · {item.width}×{item.height} · {date(item.created_at)}
                      </span>
                    </span>
                  </span>
                  {item.url ? (
                    <a href={mediaUrl(item.url)} target="_blank" rel="noreferrer">
                      <Button size="sm" variant="secondary" icon={<Download className="h-3.5 w-3.5" />}>
                        {t.common.download}
                      </Button>
                    </a>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <aside className="space-y-4">
        <Card>
          <CardTitle>{t.export.archive}</CardTitle>
          <ul className="space-y-1.5 text-[13px] text-ink-soft">
            <ArchiveRow label={t.stages.concepts} value={num(archive?.concepts?.length ?? 0)} />
            <ArchiveRow label={t.stages.script} value={archive?.approved_script ? '✓' : '—'} />
            <ArchiveRow label={t.stages.storyboard} value={num(archive?.storyboard?.scenes?.length ?? 0)} />
            <ArchiveRow label={t.wizard.assets} value={num(archive?.assets?.length ?? 0)} />
            <ArchiveRow label={t.edit.render} value={num(archive?.renders?.length ?? 0)} />
            <ArchiveRow label={t.qc.title} value={archive?.qc_score ? num(Math.round(archive.qc_score)) : '—'} />
            <ArchiveRow label={t.common.cost} value={`$${(archive?.cost?.actual_usd ?? 0).toFixed(2)}`} />
          </ul>

          <div className="mt-4 space-y-2">
            <Button
              full
              variant="secondary"
              size="sm"
              icon={<Sparkles className="h-3.5 w-3.5" />}
              loading={duplicate.pending}
              onClick={() => void duplicate.run(true)}
            >
              {t.export.newReelFrom}
            </Button>
            <Button
              full
              variant="ghost"
              size="sm"
              icon={<Copy className="h-3.5 w-3.5" />}
              loading={duplicate.pending}
              onClick={() => void duplicate.run(false)}
            >
              {t.export.duplicate}
            </Button>
            <InlineError error={duplicate.error} />
            <Link href="/projects" className="block">
              <Button full variant="ghost" size="sm" icon={<Package className="h-3.5 w-3.5" />}>
                {t.nav.projects}
              </Button>
            </Link>
          </div>
        </Card>
      </aside>
    </div>
  );
}

function ArchiveRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <li className="flex items-center justify-between">
      <span className="text-ink-muted">{label}</span>
      <span className="ltr-nums font-medium">{value}</span>
    </li>
  );
}
