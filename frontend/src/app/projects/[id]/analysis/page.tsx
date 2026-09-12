'use client';

import { CheckCircle2, Loader2, Play, RefreshCw } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';

import { AIDirector } from '@/components/AIDirector';
import { ProjectFrame } from '@/components/ProjectFrame';
import {
  Button,
  Card,
  CardTitle,
  EmptyState,
  ErrorState,
  InlineError,
  LoadingBlock,
  Stat,
} from '@/components/ui';
import { useLocale } from '@/i18n/LocaleProvider';
import { api } from '@/lib/api';
import { useApi, useMutation } from '@/lib/hooks';
import type { Analysis, ProjectDetail } from '@/lib/types';

type AnalysisPayload = {
  steps: { key: string; label_en: string; label_ar: string }[];
  analysis: Analysis | null;
  versions: { id: string; version: number }[];
  state: string;
};

export default function AnalysisPage() {
  return <ProjectFrame sidebar={() => null}>{(project, reload) => <AnalysisView project={project} reloadProject={reload} />}</ProjectFrame>;
}

function AnalysisView({ project, reloadProject }: { project: ProjectDetail; reloadProject: () => void }) {
  const { t, locale, money, num } = useLocale();
  const router = useRouter();
  const { data, error, loading, reload } = useApi<AnalysisPayload>(`/projects/${project.id}/analysis`);
  const [activeStep, setActiveStep] = useState(-1);

  const run = useMutation(async () => {
    const result = await api.post<AnalysisPayload>(`/projects/${project.id}/analysis/run`);
    reload();
    reloadProject();
    return result;
  });

  const approve = useMutation(async () => {
    await api.post(`/projects/${project.id}/analysis/approve`);
    reloadProject();
    router.push(`/projects/${project.id}/concepts`);
  });

  // Progress states while the engine works.
  useEffect(() => {
    if (!run.pending) {
      setActiveStep(-1);
      return;
    }
    setActiveStep(0);
    const steps = data?.steps.length ?? 6;
    const timer = setInterval(() => setActiveStep((current) => Math.min(current + 1, steps - 1)), 420);
    return () => clearInterval(timer);
  }, [run.pending, data?.steps.length]);

  if (loading && !data) return <LoadingBlock lines={6} />;

  const analysis = data?.analysis ?? null;
  const assets = analysis?.asset_analysis ?? {};
  const plan = analysis?.production_recommendation ?? {};

  return (
    <div className="space-y-5">
      {error ? <ErrorState error={error} onRetry={reload} /> : null}

      {/* Run panel */}
      <Card>
        <CardTitle
          action={
            <Button
              onClick={() => void run.run()}
              loading={run.pending}
              icon={analysis ? <RefreshCw className="h-4 w-4" /> : <Play className="h-4 w-4" />}
            >
              {run.pending ? t.analysis.running : analysis ? t.common.regenerate : t.analysis.run}
            </Button>
          }
        >
          {t.analysis.title}
        </CardTitle>

        <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {(data?.steps ?? []).map((step, index) => {
            const done = analysis && !run.pending ? true : activeStep > index;
            const active = run.pending && activeStep === index;
            return (
              <li
                key={step.key}
                className={`flex items-center gap-2 rounded-xl border px-3 py-2 text-[13px] transition ${
                  active
                    ? 'border-accent bg-accent-soft text-accent-dark'
                    : done
                      ? 'border-line bg-surface text-ink-soft'
                      : 'border-line bg-raised text-ink-faint'
                }`}
              >
                {active ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : done ? (
                  <CheckCircle2 className="h-3.5 w-3.5 text-ok" />
                ) : (
                  <span className="h-3.5 w-3.5 rounded-full border border-current opacity-40" />
                )}
                {locale === 'ar' ? step.label_ar : step.label_en}
              </li>
            );
          })}
        </ol>
        <InlineError error={run.error} />
      </Card>

      {!analysis ? (
        <EmptyState title={t.analysis.empty} hint={t.analysis.run} />
      ) : (
        <>
          <AIDirector notes={analysis.director_notes} />

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label={t.analysis.readiness} value={`${num(analysis.readiness_score)}%`} tone="accent" />
            <Stat label={t.analysis.confidence} value={`${num(analysis.confidence_score)}%`} />
            <Stat label={t.analysis.estimatedCost} value={money(analysis.estimated_cost_usd)} tone="ok" />
            <Stat
              label={t.analysis.recommendedMode}
              value={<span className="text-[16px]">{analysis.recommended_mode.replace(/_/g, ' ')}</span>}
            />
          </div>

          <div className="grid gap-5 lg:grid-cols-2">
            <Card>
              <CardTitle>{t.analysis.keyMessages}</CardTitle>
              <ul className="space-y-2">
                {(analysis.brief_interpretation?.key_messages ?? []).map((message: string, index: number) => (
                  <li key={index} className="flex gap-2 text-[13.5px] text-ink-soft">
                    <span className="ltr-nums text-ink-faint">{index + 1}.</span>
                    {message}
                  </li>
                ))}
              </ul>
              <div className="mt-4 space-y-2 border-t border-line pt-4 text-[13px]">
                <Row label={t.analysis.recommendedAngle} value={analysis.recommended_angle.replace(/_/g, ' ')} />
                <Row label={t.analysis.recommendedVoice} value={analysis.recommended_voice_style.replace(/_/g, ' ')} />
                <Row
                  label={t.wizard.targetAudience}
                  value={analysis.brief_interpretation?.audience_summary ?? '—'}
                />
              </div>
            </Card>

            <Card>
              <CardTitle>{t.analysis.assets}</CardTitle>
              <div className="grid grid-cols-2 gap-3">
                <MiniStat label={t.wizard.uploadImages} value={num(assets.image_count ?? 0)} />
                <MiniStat label={t.wizard.uploadVideos} value={num(assets.video_count ?? 0)} />
                <MiniStat label={t.media.usable} value={num((assets.usable_image_count ?? 0) + (assets.usable_video_count ?? 0))} />
                <MiniStat label={t.media.quality} value={`${num(assets.average_quality ?? 0)}`} />
              </div>

              <div className="mt-4 space-y-2 border-t border-line pt-4">
                <p className="section-title">{t.production.title}</p>
                <Row label={t.production.scenes} value={num(plan.scene_count ?? 0)} />
                <Row label={t.production.fromExisting} value={num(plan.scenes_from_existing_media ?? 0)} />
                <Row label={t.production.aiImage} value={num(plan.scenes_ai_image ?? 0)} />
                <Row label={t.production.aiVideo} value={num(plan.scenes_ai_video ?? 0)} />
              </div>
            </Card>
          </div>

          {(assets.per_asset ?? []).length > 0 ? (
            <Card>
              <CardTitle>{t.media.title}</CardTitle>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[560px] text-[13px]">
                  <thead>
                    <tr className="border-b border-line text-start text-[12px] text-ink-faint">
                      <th className="py-2 text-start font-medium">#</th>
                      <th className="py-2 text-start font-medium">{t.wizard.category}</th>
                      <th className="py-2 text-start font-medium">{t.media.quality}</th>
                      <th className="py-2 text-start font-medium">{t.media.hero}</th>
                      <th className="py-2 text-start font-medium">{t.analysis.assets}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(assets.per_asset ?? []).map((asset: any, index: number) => (
                      <tr key={asset.asset_id} className="border-b border-line/60">
                        <td className="ltr-nums py-2 text-ink-faint">{index + 1}</td>
                        <td className="py-2 text-ink-soft">{asset.category ?? asset.kind}</td>
                        <td className="ltr-nums py-2">{Math.round(asset.quality_score ?? asset.quality ?? 0)}</td>
                        <td className="ltr-nums py-2">{asset.hero_potential ? Math.round(asset.hero_potential) : '—'}</td>
                        <td className="py-2 text-ink-muted">
                          {asset.suggested_use ?? asset.reframing_recommendation ?? '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          ) : null}

          <div className="flex flex-wrap items-center justify-end gap-2">
            <InlineError error={approve.error} />
            <Button size="lg" loading={approve.pending} onClick={() => void approve.run()}>
              {t.analysis.approveAndContinue}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="text-[12.5px] text-ink-faint">{label}</span>
      <span className="text-end text-[13px] font-medium text-ink-soft">{value}</span>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-line bg-raised px-3 py-2.5">
      <p className="text-[11.5px] text-ink-faint">{label}</p>
      <p className="ltr-nums text-[18px] font-semibold text-ink">{value}</p>
    </div>
  );
}
