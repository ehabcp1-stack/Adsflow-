'use client';

import clsx from 'clsx';
import { CheckCircle2, KeyRound, ShieldAlert } from 'lucide-react';

import { LanguageToggle, PageHeader, useDirectorMode } from '@/components/AppShell';
import { Badge, Card, CardTitle, ErrorState, LoadingBlock, Stat, Toggle } from '@/components/ui';
import { useLocale } from '@/i18n/LocaleProvider';
import { RUNTIME_INFO } from '@/lib/api';
import { useApi } from '@/lib/hooks';
import type { ProviderStatus } from '@/lib/types';

type SettingsPayload = {
  user: { id: string; email: string; full_name: string; locale: string; director_mode: boolean };
  organization: { id: string; name: string; name_ar: string | null; parent_brand: string; monthly_budget_usd: number };
  spend: { month_spend_usd: number; monthly_target_usd: number; completed_videos: number; active_projects: number };
  providers: ProviderStatus[];
  defaults: Record<string, string | number>;
  voice_profiles: { id: string; name: string; name_ar: string; dialect: string; provider: string }[];
};

export default function SettingsPage() {
  const { t, money, num } = useLocale();
  const { directorMode, setDirectorMode } = useDirectorMode();
  const { data, error, loading, reload } = useApi<SettingsPayload>('/settings');

  if (loading && !data) return <LoadingBlock lines={6} />;
  if (error && !data) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return null;

  const byKind = data.providers.reduce<Record<string, ProviderStatus[]>>((acc, provider) => {
    (acc[provider.kind] ??= []).push(provider);
    return acc;
  }, {});

  return (
    <>
      <PageHeader title={t.settings.title} subtitle={`${data.organization.name} · ${data.organization.parent_brand}`} />

      <div className="mb-5 grid gap-4 sm:grid-cols-3">
        <Stat label={t.dashboard.monthlySpend} value={money(data.spend.month_spend_usd)} sub={`${money(data.spend.monthly_target_usd)} ${t.dashboard.ofTarget}`} tone="accent" />
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
            <Toggle checked={directorMode} onChange={setDirectorMode} label={t.common.directorMode} hint={t.settings.defaults} />
            <div className="flex items-center justify-between">
              <span className="text-[13px] text-ink-soft">{t.common.language}</span>
              <LanguageToggle />
            </div>
          </div>
        </Card>

        <Card>
          <CardTitle
            action={
              <Badge tone={RUNTIME_INFO.demoMode ? 'accent' : 'ok'}>
                {RUNTIME_INFO.appEnv}
              </Badge>
            }
          >
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

      <Card className="mt-5">
        <CardTitle
          action={
            <Badge tone={data.providers.some((p) => p.active && !p.is_mock) ? 'ok' : 'accent'}>
              {data.providers.every((p) => !p.active || p.is_mock) ? t.settings.mockMode : t.settings.active}
            </Badge>
          }
        >
          {t.settings.providers}
        </CardTitle>

        <div className="space-y-5">
          {Object.entries(byKind).map(([kind, providers]) => (
            <div key={kind}>
              <p className="section-title mb-2">{kind}</p>
              <ul className="grid gap-2 sm:grid-cols-2">
                {providers.map((provider) => (
                  <li
                    key={`${provider.kind}-${provider.name}`}
                    className={clsx(
                      'rounded-xl border px-3 py-2.5',
                      provider.active ? 'border-accent bg-accent-soft/50' : 'border-line bg-raised',
                    )}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-[13.5px] font-medium text-ink">{provider.name}</span>
                      <div className="flex items-center gap-1.5">
                        {provider.is_mock ? <Badge tone="neutral">{t.common.mock}</Badge> : null}
                        {provider.active ? <Badge tone="accent">{t.settings.active}</Badge> : null}
                      </div>
                    </div>
                    <p className="ltr-nums mt-1 truncate text-[11.5px] text-ink-faint">{provider.models.join(' · ')}</p>
                    {provider.requires_key ? (
                      <p className="ltr-nums mt-1 flex items-center gap-1.5 text-[11.5px]">
                        {provider.key_present ? (
                          <CheckCircle2 className="h-3 w-3 text-ok" />
                        ) : (
                          <ShieldAlert className="h-3 w-3 text-warn" />
                        )}
                        <span className={provider.key_present ? 'text-ok' : 'text-ink-muted'}>
                          {provider.requires_key} — {provider.key_present ? t.settings.keyPresent : t.settings.keyMissing}
                        </span>
                      </p>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <p className="mt-5 flex items-start gap-2 rounded-xl bg-canvas px-3 py-2.5 text-[12.5px] text-ink-muted">
          <KeyRound className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          Add provider keys to <code className="ltr-nums mx-1">.env</code> and set{' '}
          <code className="ltr-nums mx-1">FORCE_MOCK_PROVIDERS=false</code> to switch from mock to live adapters. Keys
          are never exposed to the browser.
        </p>
      </Card>

      <Card className="mt-5">
        <CardTitle>{t.voice.title}</CardTitle>
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
      </Card>
    </>
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
