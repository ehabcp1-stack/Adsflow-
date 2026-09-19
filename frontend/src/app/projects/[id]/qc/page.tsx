'use client';

import { AlertTriangle, Check, Play, Wrench } from 'lucide-react';
import { useRouter } from 'next/navigation';

import { ProjectFrame } from '@/components/ProjectFrame';
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
  Progress,
  ScoreRing,
} from '@/components/ui';
import { useLocale } from '@/i18n/LocaleProvider';
import { api } from '@/lib/api';
import { useApi, useMutation } from '@/lib/hooks';
import type { ProjectDetail, QCReport } from '@/lib/types';

type QCPayload = {
  report: QCReport | null;
  levels: { key: string; label_en: string; label_ar: string }[];
  weights: Record<string, number>;
  state: string;
};

export default function QCPage() {
  return <ProjectFrame>{(project, reload) => <QCView project={project} reloadProject={reload} />}</ProjectFrame>;
}

function QCView({ project, reloadProject }: { project: ProjectDetail; reloadProject: () => void }) {
  const { t, locale, num } = useLocale();
  const router = useRouter();
  const { data, error, loading, reload } = useApi<QCPayload>(`/projects/${project.id}/qc`);

  const run = useMutation(async () => {
    await api.post(`/projects/${project.id}/qc/run`);
    reload();
    reloadProject();
  });

  const autoFix = useMutation(async () => {
    await api.post(`/projects/${project.id}/qc/auto-fix`);
    reload();
    reloadProject();
  });

  const approve = useMutation(async () => {
    await api.post(`/projects/${project.id}/qc/approve`);
    reloadProject();
    router.push(`/projects/${project.id}/export`);
  });

  if (loading && !data) return <LoadingBlock lines={6} />;
  const report = data?.report ?? null;

  if (!report) {
    return (
      <div className="space-y-4">
        {error ? <ErrorState error={error} onRetry={reload} /> : null}
        <EmptyState
          title={t.qc.empty}
          action={
            <Button loading={run.pending} icon={<Play className="h-4 w-4" />} onClick={() => void run.run()}>
              {t.qc.run}
            </Button>
          }
        />
      </div>
    );
  }

  const verdictTone = report.verdict === 'approved' ? 'ok' : report.verdict === 'review' ? 'warn' : 'danger';
  const weights = data?.weights ?? {};
  // A reel assembled from no scene clips is not a draft to be improved — it is
  // nothing. Saying so once, above everything, is worth more than the eleven
  // true-but-beside-the-point complaints underneath it.
  const isPlaceholder = (report.critical_issues ?? []).some((issue) => issue.code === 'placeholder_render');

  return (
    <div className="space-y-5">
      {isPlaceholder ? (
        <div className="flex items-start gap-2.5 rounded-2xl border border-danger/25 bg-danger/[0.07] px-4 py-3">
          <AlertTriangle className="mt-0.5 h-4.5 w-4.5 shrink-0 text-danger" />
          <div>
            <p className="text-[14px] font-semibold text-danger">{t.qc.placeholder}</p>
            <p className="mt-0.5 text-[12.5px] text-ink-soft">{t.qc.placeholderHint}</p>
          </div>
        </div>
      ) : null}

      <div className="grid gap-5 lg:grid-cols-[280px_minmax(0,1fr)]">
        <Card className="flex flex-col items-center justify-center text-center">
          <ScoreRing value={report.total_score} size={120} label={t.qc.finalScore} />
          <Badge tone={verdictTone} className="mt-3">
            {t.qc[report.verdict]}
          </Badge>
          <p className="ltr-nums mt-2 text-[12px] text-ink-faint">
            v{num(report.version)} · ≥{num(report.thresholds.approve)} {t.qc.approved}
          </p>
          <Button
            size="sm"
            variant="secondary"
            className="mt-4"
            icon={<Play className="h-3.5 w-3.5" />}
            loading={run.pending}
            onClick={() => void run.run()}
          >
            {run.pending ? t.qc.running : t.qc.run}
          </Button>
        </Card>

        <Card>
          <CardTitle>{t.common.score}</CardTitle>
          {/* Weighted dimensions only, in weight order. The table used to
              render whatever `scores` happened to contain, so a model that
              answered in its own vocabulary — `cta_clarity`, `overall` — put
              rows on this screen that count for nothing, carry no weight, and
              were scored 1 because the model answered 0-1 while the bar reads
              0-100. Six dimensions are weighed; six are shown. */}
          <div className="space-y-3">
            {Object.entries(weights).map(([key, weight]) => {
              const value = report.scores[key];
              if (value === undefined) return null;
              return (
                <div key={key}>
                  <div className="mb-1 flex items-center justify-between text-[12.5px]">
                    <span className="text-ink-soft">
                      {t.qc.dimensions[key as keyof typeof t.qc.dimensions] ?? key.replace(/_/g, ' ')}
                      <span className="ltr-nums ms-1.5 text-ink-faint">×{weight}</span>
                    </span>
                    <span className="ltr-nums font-medium text-ink">{num(Math.round(value))}</span>
                  </div>
                  <Progress value={value} tone={value >= 90 ? 'ok' : value >= 85 ? 'warn' : 'danger'} />
                </div>
              );
            })}
          </div>
        </Card>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardTitle>{t.qc.title}</CardTitle>
          <ul className="space-y-2">
            {report.checks.map((check) => (
              <CheckItem key={check.level} ok={check.passed && check.score >= 85}>
                {locale === 'ar' ? check.label_ar : check.label_en}
                <span className="ltr-nums mx-2 text-ink-faint">{num(Math.round(check.score))}</span>
              </CheckItem>
            ))}
          </ul>
        </Card>

        <Card>
          <CardTitle
            action={
              report.auto_fix_plan.length > 0 ? (
                <Button size="sm" variant="secondary" icon={<Wrench className="h-3.5 w-3.5" />} loading={autoFix.pending} onClick={() => void autoFix.run()}>
                  {t.qc.autoFix}
                </Button>
              ) : null
            }
          >
            {report.critical_issues.length > 0 ? t.qc.criticalIssues : t.qc.recommendations}
          </CardTitle>

          {report.critical_issues.length > 0 ? (
            <ul className="mb-3 space-y-2">
              {report.critical_issues.map((issue) => (
                <li key={issue.code} className="flex items-start gap-2 rounded-xl bg-danger/[0.06] px-3 py-2 text-[13px] text-ink">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-danger" />
                  {locale === 'ar' ? issue.message_ar : issue.message_en ?? issue.message_ar}
                </li>
              ))}
            </ul>
          ) : null}

          <ul className="space-y-2">
            {report.recommendations.map((rec, index) => (
              <li key={`${rec.code}-${index}`} className="flex items-start gap-2 text-[13px] text-ink-soft">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-ink-faint" />
                {rec.message_ar}
              </li>
            ))}
          </ul>

          {report.auto_fix_plan.length > 0 ? (
            <div className="mt-4 rounded-xl border border-line bg-raised p-3">
              <p className="section-title mb-1.5">{t.qc.autoFix}</p>
              <ul className="space-y-1 text-[12.5px] text-ink-muted">
                {report.auto_fix_plan.map((fix, index) => (
                  <li key={`${fix.code}-${index}`}>
                    · {fix.label_ar} <span className="ltr-nums text-ink-faint">({fix.component})</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </Card>
      </div>

      <div className="flex flex-wrap items-center justify-end gap-3">
        <InlineError error={approve.error ?? autoFix.error ?? run.error} />
        <Badge tone={report.ready_to_export ? 'ok' : 'warn'}>
          {report.ready_to_export ? t.qc.readyToExport : t.qc.fix_required}
        </Badge>
        <Button size="lg" icon={<Check className="h-4 w-4" />} loading={approve.pending} onClick={() => void approve.run()}>
          {t.qc.approveFinal}
        </Button>
      </div>
    </div>
  );
}
