'use client';

import clsx from 'clsx';
import { AlertTriangle, Check, CircleDollarSign, Lock, Play, ShieldCheck } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';

import { AIDirector } from '@/components/AIDirector';
import { CostPanel } from '@/components/CostPanel';
import { ProjectFrame } from '@/components/ProjectFrame';
import { MethodBadge } from '@/components/SceneDetail';
import {
  Badge,
  Button,
  Card,
  CardTitle,
  EmptyState,
  ErrorState,
  Field,
  InlineError,
  LoadingBlock,
  Modal,
  Progress,
  Stat,
} from '@/components/ui';
import { useLocale } from '@/i18n/LocaleProvider';
import { api, mediaUrl } from '@/lib/api';
import { useApi, useMutation } from '@/lib/hooks';
import type { BudgetSnapshot, ProductionPlan, ProductionStatus, ProjectDetail } from '@/lib/types';

type ProductionPayload = {
  plan: ProductionPlan | null;
  budget: BudgetSnapshot;
  status: ProductionStatus | null;
  approvals: Record<string, { status: string }>;
  state: string;
};

export default function ProductionPage() {
  return <ProjectFrame>{(project, reload) => <ProductionView project={project} reloadProject={reload} />}</ProjectFrame>;
}

function ProductionView({ project, reloadProject }: { project: ProjectDetail; reloadProject: () => void }) {
  const { t, money, num } = useLocale();
  const router = useRouter();
  const generating = project.state === 'GENERATING';
  const { data, error, loading, reload } = useApi<ProductionPayload>(`/projects/${project.id}/production`, {
    pollMs: generating ? 1500 : undefined,
  });
  const [budgetOpen, setBudgetOpen] = useState(false);
  const [newBudget, setNewBudget] = useState(String(project.budget_limit_usd));

  const approvePlan = useMutation(async () => {
    await api.post(`/projects/${project.id}/production/approve`);
    reload();
    reloadProject();
  });

  const start = useMutation(async () => {
    await api.post(`/projects/${project.id}/production/start`);
    reload();
    reloadProject();
  });

  const finish = useMutation(async () => {
    await api.post(`/projects/${project.id}/production/finish`);
    await api.post(`/projects/${project.id}/edit/render`);
    reloadProject();
    router.push(`/projects/${project.id}/edit`);
  });

  // Hero-frame-first gate: approving the still is what releases the paid
  // video job for that scene, so this reloads status immediately after.
  const keyframe = useMutation(async (sceneId: string) => {
    await api.post(`/projects/${project.id}/scenes/${sceneId}/keyframe/approve`);
    reload();
  });

  const raiseBudget = useMutation(async () => {
    await api.post(`/projects/${project.id}/budget`, { budget_limit_usd: Number(newBudget) });
    setBudgetOpen(false);
    reload();
    reloadProject();
  });

  if (loading && !data) return <LoadingBlock lines={6} />;
  const plan = data?.plan ?? null;
  const status = data?.status ?? null;
  const planApproved = data?.approvals?.production_plan?.status === 'approved';

  if (!plan) {
    // A plan only exists once the storyboard does — point there instead of
    // leaving a dead screen.
    return (
      <div className="space-y-4">
        {error ? <ErrorState error={error} onRetry={reload} /> : null}
        <EmptyState
          title={t.production.empty}
          hint={t.storyboard.empty}
          action={
            <Link href={`/projects/${project.id}/storyboard`}>
              <Button>{t.storyboard.title}</Button>
            </Link>
          }
        />
      </div>
    );
  }

  const safe = plan.status === 'safe_to_generate';

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-[18px] font-semibold text-ink">{t.production.title}</h2>
          <p className="text-[13px] text-ink-muted">{t.production.beforeYouSpend}</p>
        </div>
        <Badge tone={safe ? 'ok' : 'warn'} icon={safe ? <ShieldCheck className="h-3.5 w-3.5" /> : <AlertTriangle className="h-3.5 w-3.5" />}>
          {safe ? t.production.safe : t.production.needsApproval}
        </Badge>
      </div>

      <AIDirector notes={plan.director_notes} />

      {/* Plan breakdown */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label={t.production.scenes} value={num(plan.scene_count)} />
        <Stat label={t.production.fromExisting} value={num(plan.counts.existing_media + plan.counts.photo_motion)} tone="ok" />
        <Stat label={t.production.aiImage} value={num(plan.counts.ai_image)} />
        <Stat label={t.production.aiVideo} value={num(plan.counts.ai_video)} tone={plan.counts.ai_video > 1 ? 'warn' : 'neutral'} />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardTitle>{t.common.cost}</CardTitle>
          <dl className="space-y-2 text-[13.5px]">
            <CostRow label={t.production.voiceCost} value={money(plan.voice_cost_usd)} />
            <CostRow label={t.production.videoCost} value={money(plan.video_cost_usd)} />
            <CostRow label={t.production.imageCost} value={money(plan.image_cost_usd)} />
            <CostRow label={t.production.photoMotion} value={money(plan.photo_motion_cost_usd)} />
            <CostRow label={t.production.musicCost} value={money(plan.music_cost_usd)} />
            <CostRow label={t.production.reserve} value={money(plan.regeneration_reserve_usd)} muted />
            <div className="flex items-center justify-between border-t border-line pt-2 text-[15px] font-semibold">
              <dt>{t.production.total}</dt>
              <dd className="ltr-nums">{money(plan.estimated_total_usd)}</dd>
            </div>
            <div className="flex items-center justify-between text-[13px] text-ink-muted">
              <dt>{t.common.budget}</dt>
              <dd className="ltr-nums">{money(plan.budget_limit_usd)}</dd>
            </div>
          </dl>

          {!safe ? (
            <Button
              variant="secondary"
              size="sm"
              className="mt-3"
              icon={<CircleDollarSign className="h-3.5 w-3.5" />}
              onClick={() => setBudgetOpen(true)}
            >
              {t.common.budget}
            </Button>
          ) : null}
        </Card>

        <Card>
          <CardTitle>{t.production.order}</CardTitle>
          <ol className="space-y-2">
            {plan.generation_order.map((item, index) => (
              <li key={item.scene_id} className="flex items-start gap-2.5 text-[13px]">
                <span className="ltr-nums mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-canvas text-[11px] font-semibold text-ink-soft">
                  {index + 1}
                </span>
                <span>
                  <span className="font-medium text-ink">
                    {t.storyboard.title} {item.scene_number}
                  </span>
                  <span className="block text-[12px] text-ink-muted">{item.reason_ar}</span>
                </span>
              </li>
            ))}
          </ol>
        </Card>
      </div>

      {/* What has actually been spent, from the cost ledger. */}
      <CostPanel projectId={project.id} sceneCount={plan.scene_count} />

      {/* Generation */}
      {status && status.jobs_total > 0 ? (
        <Card>
          <CardTitle
            action={
              <Badge tone={status.all_done ? 'ok' : 'accent'}>
                <span className="ltr-nums">
                  {num(status.jobs_completed)}/{num(status.jobs_total)}
                </span>{' '}
                {t.production.jobs}
              </Badge>
            }
          >
            {t.production.generating}
          </CardTitle>

          <Progress value={status.progress * 100} tone={status.jobs_failed ? 'warn' : 'accent'} className="mb-4" />

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {status.jobs.map((job) => (
              <div key={job.id} className="rounded-xl border border-line bg-raised p-3">
                <div className="mb-1 flex items-center justify-between">
                  <span className="text-[12.5px] font-medium text-ink">{job.type.replace(/_/g, ' ')}</span>
                  <Badge
                    tone={
                      job.status === 'completed' ? 'ok' : job.status === 'failed' ? 'danger' : job.status === 'running' ? 'accent' : 'neutral'
                    }
                  >
                    {job.status}
                  </Badge>
                </div>
                <Progress value={job.progress * 100} tone={job.status === 'failed' ? 'danger' : 'accent'} />
                <p className="mt-1.5 truncate text-[11.5px] text-ink-faint">{job.label || job.error || '—'}</p>
              </div>
            ))}
          </div>

          {status.scenes.length > 0 ? (
            <div className="mt-5">
              <p className="section-title mb-2">{t.storyboard.scenes}</p>
              <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
                {status.scenes.map((scene) => (
                  <div
                    key={scene.id}
                    className={clsx(
                      'overflow-hidden rounded-xl border',
                      scene.awaiting_keyframe_approval ? 'border-accent' : 'border-line',
                    )}
                  >
                    <div className="relative aspect-[9/16] bg-graphite-900">
                      <img
                        src={mediaUrl(scene.thumbnail_url || scene.keyframe_url)}
                        alt=""
                        className="h-full w-full object-cover"
                      />
                      <span className="ltr-nums absolute start-1.5 top-1.5 rounded bg-black/60 px-1.5 text-[10px] font-bold text-white">
                        {scene.scene_number}
                      </span>
                      {scene.locked ? <Lock className="absolute end-1.5 top-1.5 h-3 w-3 text-emerald-400" /> : null}
                    </div>
                    <div className="p-2">
                      <div className="flex items-center justify-between text-[11px]">
                        <span className={clsx(scene.status === 'approved' || scene.status === 'locked' ? 'text-ok' : 'text-ink-muted')}>
                          {scene.status}
                        </span>
                        <span className="ltr-nums text-ink-faint">{scene.quality_score ? num(scene.quality_score) : '—'}</span>
                      </div>
                      <MethodBadge method={scene.production_method} />
                      {/*
                        The whole point of hero-frame-first: the video is not
                        bought until someone looks at this still and says yes.
                      */}
                      {scene.awaiting_keyframe_approval ? (
                        <div className="mt-2 border-t border-line pt-2">
                          <p className="mb-1.5 text-[11px] leading-snug text-accent">
                            {t.production.keyframeWaiting}
                          </p>
                          <Button
                            size="sm"
                            className="w-full"
                            disabled={keyframe.pending}
                            onClick={() => void keyframe.run(scene.id)}
                          >
                            {t.production.approveKeyframe}
                          </Button>
                        </div>
                      ) : null}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </Card>
      ) : null}

      {/* Primary actions */}
      <div className="flex flex-wrap items-center justify-end gap-3">
        <InlineError error={approvePlan.error ?? start.error ?? finish.error} />
        {!planApproved ? (
          <Button size="lg" icon={<Check className="h-4 w-4" />} loading={approvePlan.pending} onClick={() => void approvePlan.run()}>
            {t.production.approvePlan}
          </Button>
        ) : !status || status.jobs_total === 0 ? (
          <Button size="lg" icon={<Play className="h-4 w-4" />} loading={start.pending} onClick={() => void start.run()}>
            {t.production.start}
          </Button>
        ) : (
          <Button
            size="lg"
            disabled={!status.all_done}
            loading={finish.pending}
            icon={<Check className="h-4 w-4" />}
            onClick={() => void finish.run()}
          >
            {t.edit.render}
          </Button>
        )}
      </div>

      <Modal
        open={budgetOpen}
        onClose={() => setBudgetOpen(false)}
        title={t.common.budget}
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setBudgetOpen(false)}>
              {t.common.cancel}
            </Button>
            <Button loading={raiseBudget.pending} onClick={() => void raiseBudget.run()}>
              {t.common.approve}
            </Button>
          </div>
        }
      >
        <p className="mb-3 text-[13.5px] text-ink-muted">
          {t.production.total}: <span className="ltr-nums font-semibold text-ink">{money(plan.estimated_total_usd)}</span>
        </p>
        <Field label={t.costs.budget} hint={t.production.needsApproval}>
          <input
            type="number"
            min="0"
            step="0.5"
            className="field ltr-nums"
            value={newBudget}
            onChange={(event) => setNewBudget(event.target.value)}
          />
        </Field>
        <InlineError error={raiseBudget.error} />
      </Modal>
    </div>
  );
}

function CostRow({ label, value, muted }: { label: string; value: string; muted?: boolean }) {
  return (
    <div className={clsx('flex items-center justify-between', muted && 'text-ink-muted')}>
      <dt>{label}</dt>
      <dd className="ltr-nums font-medium">{value}</dd>
    </div>
  );
}
