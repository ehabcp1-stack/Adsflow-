'use client';

import clsx from 'clsx';
import {
  Boxes,
  CheckCircle2,
  CircleSlash,
  Gauge,
  Image as ImageIcon,
  KeyRound,
  Mic,
  Music,
  ShieldAlert,
  Sparkles,
  Video,
} from 'lucide-react';

import { LanguageToggle, PageHeader, useDirectorMode } from '@/components/AppShell';
import { Badge, Card, CardTitle, ErrorState, LoadingBlock, Skeleton, Stat, Toggle } from '@/components/ui';
import { useLocale } from '@/i18n/LocaleProvider';
import { RUNTIME_INFO } from '@/lib/api';
import { useApi } from '@/lib/hooks';
import type { SystemHealth, SystemModel, SystemProviders } from '@/lib/types';

type SettingsPayload = {
  user: { id: string; email: string; full_name: string; locale: string; director_mode: boolean };
  organization: { id: string; name: string; name_ar: string | null; parent_brand: string; monthly_budget_usd: number };
  spend: { month_spend_usd: number; monthly_target_usd: number; completed_videos: number; active_projects: number };
  defaults: Record<string, string | number>;
  voice_profiles: { id: string; name: string; name_ar: string; dialect: string; provider: string }[];
};

const KIND_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  llm: Sparkles,
  image: ImageIcon,
  video: Video,
  voice: Mic,
  music: Music,
};

/** Capability labels are product vocabulary (LLM · Image · …), not prose. */
const KIND_LABEL: Record<string, string> = {
  llm: 'LLM',
  image: 'Image',
  video: 'Video',
  voice: 'Voice',
  music: 'Music',
};

export default function SettingsPage() {
  const { t, money, num } = useLocale();
  const { directorMode, setDirectorMode } = useDirectorMode();
  const { data, error, loading, reload } = useApi<SettingsPayload>('/settings');
  const providers = useApi<SystemProviders>('/system/providers');
  const health = useApi<SystemHealth>('/system/health');

  if (loading && !data) return <LoadingBlock lines={6} />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;

  return (
    <>
      <PageHeader title={t.settings.title} subtitle={`${data.organization.name} · ${data.organization.parent_brand}`} />

      <div className="mb-5 grid gap-4 sm:grid-cols-3">
        <Stat
          label={t.dashboard.monthlySpend}
          value={money(data.spend.month_spend_usd)}
          sub={`${money(data.spend.monthly_target_usd)} ${t.dashboard.ofTarget}`}
          tone="accent"
        />
        <Stat label={t.dashboard.completed} value={num(data.spend.completed_videos)} tone="ok" />
        <Stat label={t.dashboard.activeProjects} value={num(data.spend.active_projects)} />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardTitle>{t.settings.account}</CardTitle>
          <dl className="space-y-2 text-[13px]">
            <Row label="email" value={data.user.email} />
            <Row label="name" value={data.user.full_name || '—'} />
            <Row label={t.settings.organization} value={data.organization.name_ar || data.organization.name} />
          </dl>
          <div className="mt-4 space-y-3 border-t border-line pt-4">
            <Toggle
              checked={directorMode}
              onChange={setDirectorMode}
              label={t.common.directorMode}
              hint={t.director.autoSmartHint}
            />
            <div className="flex items-center justify-between">
              <span className="text-[13px] text-ink-soft">{t.common.language}</span>
              <LanguageToggle />
            </div>
          </div>
        </Card>

        {/* Runtime block — unchanged contract: runtime mode + api base url. */}
        <Card>
          <CardTitle action={<Badge tone={RUNTIME_INFO.demoMode ? 'accent' : 'ok'}>{RUNTIME_INFO.appEnv}</Badge>}>
            {t.settings.defaults}
          </CardTitle>
          <dl className="space-y-2 text-[13px]">
            <Row label="runtime mode" value={RUNTIME_INFO.appEnv} />
            <Row label="api base url" value={RUNTIME_INFO.apiBaseUrl ?? '— (mock snapshot)'} />
            {Object.entries(data.defaults).map(([key, value]) => (
              <Row key={key} label={key.replace(/_/g, ' ')} value={String(value)} />
            ))}
          </dl>
        </Card>
      </div>

      {/* ------------------------------------------------- System health */}
      <Card className="mt-5">
        <CardTitle
          action={
            health.data ? (
              <Badge tone={health.data.runtime_mode === 'real' ? 'ok' : 'accent'}>
                {health.data.runtime_mode === 'real' ? t.settings.realProvider : t.settings.mockMode}
              </Badge>
            ) : null
          }
        >
          {t.settings.runtimeHealth}
        </CardTitle>

        {health.loading && !health.data ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {[0, 1, 2, 3, 4, 5].map((index) => (
              <Skeleton key={index} className="h-[52px]" />
            ))}
          </div>
        ) : health.error ? (
          <ErrorState error={health.error} onRetry={health.reload} />
        ) : health.data ? (
          <>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <Fact label="env" value={health.data.env} />
              <Fact label={t.settings.storage} value={health.data.storage_backend} />
              <Fact label={t.settings.jobs} value={health.data.job_backend} />
              <Fact
                label={t.settings.localRender}
                value={health.data.local_render_enabled ? t.settings.enabled : t.settings.disabled}
                ok={health.data.local_render_enabled}
              />
              <Fact
                label={t.settings.ffmpeg}
                value={health.data.ffmpeg_available ? t.settings.present : t.settings.missing}
                ok={health.data.ffmpeg_available}
              />
              <Fact
                label={t.settings.ffprobe}
                value={health.data.ffprobe_available ? t.settings.present : t.settings.missing}
                ok={health.data.ffprobe_available}
              />
            </div>
            {health.data.force_mock_providers ? (
              <p className="mt-4 text-[12.5px] text-ink-muted">{t.settings.mockRuntimeNote}</p>
            ) : null}
          </>
        ) : null}
      </Card>

      {/* ---------------------------------------------------- Providers */}
      <Card className="mt-5">
        <CardTitle
          action={
            providers.data ? (
              <div className="flex flex-wrap items-center gap-1.5">
                <Badge tone="neutral">
                  <span className="ltr-nums">{num(providers.data.totals.models)}</span> {t.settings.modelsCount}
                </Badge>
                <Badge tone={providers.data.totals.configured > 0 ? 'ok' : 'accent'}>
                  <span className="ltr-nums">{num(providers.data.totals.configured)}</span> {t.settings.configured}
                </Badge>
              </div>
            ) : null
          }
        >
          {t.settings.providers}
        </CardTitle>
        <p className="-mt-2 mb-4 text-[13px] text-ink-muted">{t.settings.providersSubtitle}</p>

        {providers.loading && !providers.data ? (
          <LoadingBlock lines={6} />
        ) : providers.error ? (
          <ErrorState error={providers.error} onRetry={providers.reload} />
        ) : providers.data ? (
          <div className="space-y-6">
            {providers.data.kinds.map((kind) => {
              const models = providers.data?.by_kind[kind] ?? [];
              const Icon = KIND_ICON[kind] ?? Boxes;
              return (
                <section key={kind}>
                  <div className="mb-2.5 flex items-center gap-2">
                    <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-canvas text-ink-soft">
                      <Icon className="h-3.5 w-3.5" />
                    </span>
                    <h4 className="text-[14px] font-semibold text-ink">{KIND_LABEL[kind] ?? kind}</h4>
                    <span className="ltr-nums text-[12px] text-ink-faint">
                      {num(models.length)} {t.settings.modelsCount}
                    </span>
                  </div>

                  {models.length === 0 ? (
                    <p className="text-[13px] text-ink-muted">{t.settings.noModels}</p>
                  ) : (
                    <ul className="grid gap-2.5 lg:grid-cols-2">
                      {models.map((model) => (
                        <ModelRow key={`${model.provider}-${model.model_id}`} model={model} />
                      ))}
                    </ul>
                  )}
                </section>
              );
            })}
          </div>
        ) : null}

        {/* One-line instruction: keys live on the backend host, never Netlify. */}
        <p className="mt-6 flex items-start gap-2 rounded-xl bg-canvas px-3.5 py-3 text-[12.5px] leading-relaxed text-ink-muted">
          <KeyRound className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {t.settings.enableHint}
        </p>
      </Card>

      <Card className="mt-5">
        <CardTitle>{t.voice.title}</CardTitle>
        {data.voice_profiles.length === 0 ? (
          <p className="text-[13px] text-ink-muted">{t.voice.empty}</p>
        ) : (
          <ul className="grid gap-2 sm:grid-cols-2">
            {data.voice_profiles.map((profile) => (
              <li key={profile.id} className="rounded-xl border border-line bg-raised px-3 py-2 text-[13px]">
                <span className="font-medium text-ink">{profile.name_ar || profile.name}</span>
                <span className="ltr-nums block text-[11.5px] text-ink-faint">
                  {profile.dialect} · {profile.provider}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}

/* ----------------------------------------------------------- Model row */
function ModelRow({ model }: { model: SystemModel }) {
  const { t, num, locale } = useLocale();
  const notes = locale === 'ar' ? model.notes_ar || model.notes_en : model.notes_en || model.notes_ar;

  return (
    <li
      className={clsx(
        'rounded-xl border px-3.5 py-3',
        model.is_default ? 'border-accent bg-accent-soft/40' : 'border-line bg-raised',
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-[13.5px] font-semibold text-ink">{model.display_name}</p>
          <p className="ltr-nums truncate text-[11.5px] text-ink-faint">
            {model.provider} · {model.model_id}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-1">
          {model.deprecated ? <Badge tone="warn">{t.settings.retiredModel}</Badge> : null}
          {model.is_default ? <Badge tone="accent">{t.settings.defaultModel}</Badge> : null}
          <Badge tone={model.is_mock ? 'neutral' : 'dark'}>
            {model.is_mock ? t.common.mock : t.settings.realProvider}
          </Badge>
        </div>
      </div>

      {/*
        Provenance. A model id is configuration, not fact — the operator has to
        be able to tell, without reading the source, whether anyone ever
        checked this string against the vendor.
      */}
      {!model.is_mock ? (
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
          {model.deprecated ? (
            <span className="flex items-center gap-1.5 text-warn">
              <ShieldAlert className="h-3 w-3" />
              {t.settings.retiredOn} <span className="ltr-nums">{model.sunset_date}</span>
            </span>
          ) : model.verified_at ? (
            <span className="flex items-center gap-1.5 text-ok">
              <CheckCircle2 className="h-3 w-3" />
              {t.settings.verifiedOn} <span className="ltr-nums">{model.verified_at}</span>
            </span>
          ) : (
            <span className="flex items-center gap-1.5 text-warn">
              <ShieldAlert className="h-3 w-3" />
              {t.settings.unverifiedModel} — {t.settings.unverifiedHint}
            </span>
          )}
          {model.docs_url ? (
            <a
              href={model.docs_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-accent underline-offset-2 hover:underline"
            >
              {t.settings.vendorDocs}
            </a>
          ) : null}
        </div>
      ) : null}

      {/* Configured / healthy — never a key value, only its presence. */}
      <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[11.5px]">
        <span className={clsx('flex items-center gap-1.5', model.configured ? 'text-ok' : 'text-ink-muted')}>
          {model.configured ? <CheckCircle2 className="h-3 w-3" /> : <ShieldAlert className="h-3 w-3 text-warn" />}
          {model.configured ? t.settings.configured : t.settings.notConfigured}
        </span>
        <span className={clsx('flex items-center gap-1.5', model.healthy ? 'text-ok' : 'text-ink-muted')}>
          {model.healthy ? <Gauge className="h-3 w-3" /> : <CircleSlash className="h-3 w-3" />}
          {model.healthy ? t.settings.healthy : t.settings.unavailable}
        </span>
        {model.requires_key ? (
          <span className="ltr-nums text-ink-faint">
            {t.settings.keyVariable}: <code className="text-ink-muted">{model.requires_key}</code>
          </span>
        ) : null}
      </div>

      <dl className="mt-2.5 grid grid-cols-2 gap-x-4 gap-y-1 border-t border-line/70 pt-2.5 text-[11.5px] sm:grid-cols-4">
        <Meta label={t.settings.qualityTier} value={model.quality_tier} />
        <Meta label={t.settings.latencyTier} value={model.latency_tier} />
        <Meta label={t.settings.fallbackOrder} value={<span className="ltr-nums">{num(model.fallback_priority)}</span>} />
        <Meta
          label={t.settings.price}
          value={
            model.cost_per_unit === 0 ? (
              t.common.free
            ) : (
              <span className="ltr-nums">
                ${model.cost_per_unit} / {model.cost_unit.replace(/_/g, ' ')}
              </span>
            )
          }
        />
      </dl>

      {model.capabilities.length > 0 ? (
        <p className="ltr-nums mt-2 truncate text-[11px] text-ink-faint">
          {model.capabilities.map((capability) => capability.replace(/_/g, ' ')).join(' · ')}
        </p>
      ) : null}

      {notes ? <p className="mt-1.5 text-[11.5px] leading-relaxed text-ink-muted">{notes}</p> : null}

      {model.last_error ? (
        <p className="ltr-nums mt-1.5 truncate text-[11px] text-danger">
          {t.settings.lastError}: {model.last_error}
        </p>
      ) : null}
    </li>
  );
}

function Meta({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-ink-faint">{label}</dt>
      <dd className="font-medium text-ink-soft">{value}</dd>
    </div>
  );
}

function Fact({ label, value, ok }: { label: string; value: string; ok?: boolean }) {
  return (
    <div className="rounded-xl border border-line bg-raised px-3 py-2.5">
      <p className="text-[11.5px] text-ink-faint">{label}</p>
      <p
        className={clsx(
          'ltr-nums text-[13.5px] font-medium',
          ok === undefined ? 'text-ink-soft' : ok ? 'text-ok' : 'text-warn',
        )}
      >
        {value}
      </p>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <dt className="text-ink-faint">{label}</dt>
      <dd className="ltr-nums truncate ps-3 font-medium text-ink-soft">{value}</dd>
    </div>
  );
}
