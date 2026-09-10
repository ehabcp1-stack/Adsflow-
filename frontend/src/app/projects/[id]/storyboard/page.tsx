'use client';

import clsx from 'clsx';
import { Check, Lock, Wand2 } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useState } from 'react';

import { AIDirector } from '@/components/AIDirector';
import { ProjectFrame } from '@/components/ProjectFrame';
import { MethodBadge, SceneDetail } from '@/components/SceneDetail';
import {
  Badge,
  Button,
  Card,
  CardTitle,
  CheckItem,
  EmptyState,
  ErrorState,
  InlineError,
  LoadingBlock,
} from '@/components/ui';
import { useLocale } from '@/i18n/LocaleProvider';
import { api, mediaUrl } from '@/lib/api';
import { useApi, useMutation } from '@/lib/hooks';
import type { ProjectDetail, Scene, Storyboard } from '@/lib/types';

export default function StoryboardPage() {
  return <ProjectFrame>{(project, reload) => <StoryboardView project={project} reloadProject={reload} />}</ProjectFrame>;
}

function StoryboardView({ project, reloadProject }: { project: ProjectDetail; reloadProject: () => void }) {
  const { t, money, num, timecode } = useLocale();
  const router = useRouter();
  const { data, error, loading, reload } = useApi<{ storyboard: Storyboard | null }>(
    `/projects/${project.id}/storyboard`,
  );
  const [openScene, setOpenScene] = useState<Scene | null>(null);

  const build = useMutation(async (regenerate = false) => {
    await api.post(`/projects/${project.id}/storyboard/generate${regenerate ? '?regenerate=true' : ''}`);
    reload();
    reloadProject();
  });

  const sceneAction = useMutation(async (scene: Scene, action: string, payload?: Record<string, unknown>) => {
    const base = `/projects/${project.id}/scenes/${scene.id}`;
    if (action === 'cheaper') await api.post(`${base}/cheaper`);
    else if (action === 'premium') await api.post(`${base}/premium`);
    else if (action === 'lock') await api.post(`${base}/lock`, payload);
    else if (action === 'regenerate') await api.post(`${base}/regenerate`);
    else if (action === 'update') await api.patch(base, { changes: payload });
    const fresh = await api.get<{ storyboard: Storyboard | null }>(`/projects/${project.id}/storyboard`);
    const updated = fresh.storyboard?.scenes.find((item) => item.id === scene.id) ?? null;
    setOpenScene(updated);
    reload();
    reloadProject();
  });

  const approve = useMutation(async () => {
    await api.post(`/projects/${project.id}/storyboard/approve`);
    reloadProject();
    router.push(`/projects/${project.id}/production`);
  });

  if (loading && !data) return <LoadingBlock lines={6} />;

  const storyboard = data?.storyboard ?? null;

  if (!storyboard) {
    return (
      <div className="space-y-4">
        {error ? <ErrorState error={error} onRetry={reload} /> : null}
        {build.error ? <ErrorState error={build.error} /> : null}
        <EmptyState
          title={t.storyboard.empty}
          action={
            <Button loading={build.pending} icon={<Wand2 className="h-4 w-4" />} onClick={() => void build.run(false)}>
              {t.common.generate}
            </Button>
          }
        />
      </div>
    );
  }

  const total = storyboard.total_duration_sec || 1;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <h2 className="text-[18px] font-semibold text-ink">{t.storyboard.title}</h2>
          <Badge tone="neutral">
            <span className="ltr-nums">{num(storyboard.scenes.length)}</span> {t.storyboard.scenes}
          </Badge>
          <Badge tone="neutral">
            <span className="ltr-nums">v{num(storyboard.version)}</span>
          </Badge>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="secondary" loading={build.pending} onClick={() => void build.run(true)}>
            {t.common.regenerate}
          </Button>
        </div>
      </div>

      <AIDirector notes={storyboard.production_plan?.director_notes} />

      {/* Dark graphite timeline workspace */}
      <div className="workspace p-4">
        <div className="mb-3 flex items-center justify-between">
          <span className="text-[13px] font-semibold text-slate-200">{t.storyboard.timeline}</span>
          <span className="ltr-nums text-[12px] text-slate-400">{timecode(storyboard.total_duration_sec)}</span>
        </div>

        <div className="flex gap-1 overflow-hidden rounded-lg">
          {storyboard.scenes.map((scene) => (
            <button
              key={scene.id}
              type="button"
              onClick={() => setOpenScene(scene)}
              title={`${scene.scene_number}. ${scene.purpose}`}
              style={{ flexGrow: (scene.end_time - scene.start_time) / total }}
              className={clsx(
                'group relative h-16 min-w-[28px] overflow-hidden rounded-md border transition',
                scene.locked ? 'border-emerald-500/60' : 'border-graphite-line hover:border-accent',
              )}
            >
              <img
                src={mediaUrl(scene.thumbnail_url || scene.keyframe_url)}
                alt=""
                className="h-full w-full object-cover opacity-80 transition group-hover:opacity-100"
              />
              <span className="ltr-nums absolute start-1 top-1 rounded bg-black/60 px-1 text-[10px] font-semibold text-white">
                {scene.scene_number}
              </span>
              {scene.locked ? (
                <Lock className="absolute end-1 top-1 h-3 w-3 text-emerald-400" />
              ) : null}
            </button>
          ))}
        </div>

        <div className="mt-3 flex flex-wrap gap-3 text-[11.5px] text-slate-400">
          <span>■ original media</span>
          <span>■ photo motion</span>
          <span>■ AI image</span>
          <span>■ AI video</span>
        </div>
      </div>

      {/* Scene grid */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {storyboard.scenes.map((scene) => (
          <article
            key={scene.id}
            onClick={() => setOpenScene(scene)}
            className="card card-hover cursor-pointer overflow-hidden p-0"
          >
            <div className="relative aspect-[9/16] bg-graphite-900">
              <img
                src={mediaUrl(scene.output_url && !scene.output_url.endsWith('.mp4') ? scene.output_url : scene.thumbnail_url)}
                alt={scene.purpose}
                className="h-full w-full object-cover"
              />
              <span className="ltr-nums absolute start-2 top-2 rounded-lg bg-black/60 px-1.5 py-0.5 text-[11px] font-bold text-white">
                {scene.scene_number}
              </span>
              <span className="absolute end-2 top-2 flex flex-col items-end gap-1">
                {scene.is_hook ? <Badge tone="accent">hook</Badge> : null}
                {scene.is_hero ? <Badge tone="gold">hero</Badge> : null}
                {scene.locked ? <Badge tone="ok">{t.common.locked}</Badge> : null}
              </span>
              <span className="ltr-nums absolute bottom-2 start-2 rounded bg-black/60 px-1.5 py-0.5 text-[10.5px] text-white">
                {timecode(scene.start_time)} → {timecode(scene.end_time)}
              </span>
            </div>
            <div className="p-3">
              <p className="truncate text-[13px] font-medium text-ink">{scene.purpose}</p>
              <p className="mt-0.5 line-clamp-2 text-[12px] text-ink-muted">{scene.voice_line}</p>
              <div className="mt-2.5 flex items-center justify-between">
                <MethodBadge method={scene.production_method} />
                <span className="ltr-nums text-[12px] font-medium text-ink-soft">{money(scene.estimated_cost_usd)}</span>
              </div>
            </div>
          </article>
        ))}
      </div>

      {/* Continuity + plan */}
      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardTitle
            action={
              <Badge tone={storyboard.continuity_report.score >= 80 ? 'ok' : 'warn'}>
                <span className="ltr-nums">{num(storyboard.continuity_report.score)}%</span>
              </Badge>
            }
          >
            {t.storyboard.continuity}
          </CardTitle>
          <ul className="space-y-2">
            {storyboard.continuity_report.checks.map((check) => (
              <CheckItem key={check.key} ok={check.ok}>
                {check.message_ar}
              </CheckItem>
            ))}
          </ul>
        </Card>

        <Card>
          <CardTitle>{t.production.title}</CardTitle>
          <dl className="space-y-2 text-[13px]">
            {Object.entries(storyboard.production_plan?.counts ?? {}).map(([key, value]) => (
              <div key={key} className="flex items-center justify-between">
                <dt className="text-ink-muted">{key.replace(/_/g, ' ')}</dt>
                <dd className="ltr-nums font-medium text-ink-soft">{num(value)}</dd>
              </div>
            ))}
            <div className="flex items-center justify-between border-t border-line pt-2">
              <dt className="font-medium text-ink">{t.production.total}</dt>
              <dd className="ltr-nums font-semibold text-ink">
                {money(storyboard.production_plan?.estimated_total_usd ?? 0)}
              </dd>
            </div>
          </dl>
        </Card>
      </div>

      <div className="flex flex-wrap items-center justify-end gap-3">
        <InlineError error={approve.error} />
        <Button size="lg" icon={<Check className="h-4 w-4" />} loading={approve.pending} onClick={() => void approve.run()}>
          {t.storyboard.approve}
        </Button>
      </div>

      <SceneDetail
        scene={openScene}
        open={Boolean(openScene)}
        onClose={() => setOpenScene(null)}
        pending={sceneAction.pending}
        error={sceneAction.error}
        onAction={(action, payload) => openScene && void sceneAction.run(openScene, action, payload)}
      />
    </div>
  );
}
