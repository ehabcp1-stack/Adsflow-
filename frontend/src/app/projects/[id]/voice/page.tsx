'use client';

import clsx from 'clsx';
import { Lock, Mic, Play, Volume2 } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useState } from 'react';

import { AIDirector } from '@/components/AIDirector';
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
  Slider,
} from '@/components/ui';
import { useLocale } from '@/i18n/LocaleProvider';
import { api, mediaUrl } from '@/lib/api';
import { useApi, useMutation } from '@/lib/hooks';
import type { DirectorNote, ProjectDetail, VoiceProfile } from '@/lib/types';

type VoicePayload = {
  profiles: VoiceProfile[];
  selected_voice_profile_id: string | null;
  voice_locked: boolean;
  voice_over_enabled: boolean;
  sample_text: string;
  timing: { index: number; role: string; voice_line: string; start: number; end: number }[];
  pronunciation: Record<string, any>;
  director_notes: DirectorNote[];
  state: string;
};

export default function VoicePage() {
  return <ProjectFrame>{(project, reload) => <VoiceView project={project} reloadProject={reload} />}</ProjectFrame>;
}

function VoiceView({ project, reloadProject }: { project: ProjectDetail; reloadProject: () => void }) {
  const { t, locale, timecode, money } = useLocale();
  const router = useRouter();
  const { data, error, loading, reload } = useApi<VoicePayload>(`/projects/${project.id}/voice`);
  const [active, setActive] = useState<string | null>(null);
  const [speed, setSpeed] = useState(1);
  const [energy, setEnergy] = useState(0.6);
  const [emotion, setEmotion] = useState(0.5);
  const [preview, setPreview] = useState<{ url?: string; duration?: number; cost?: number } | null>(null);

  const selectedId = active ?? data?.selected_voice_profile_id ?? data?.profiles[0]?.id ?? null;

  const doPreview = useMutation(async (profileId: string) => {
    const result = await api.post<{ url: string; duration_sec: number; estimated_cost_usd: number; is_mock: boolean }>(
      `/projects/${project.id}/voice/preview`,
      { voice_profile_id: profileId, speed, energy, emotion },
    );
    setPreview({ url: mediaUrl(result.url), duration: result.duration_sec, cost: result.estimated_cost_usd });
    return result;
  });

  const lock = useMutation(async (profileId: string, doLock: boolean) => {
    await api.post(`/projects/${project.id}/voice/select`, {
      voice_profile_id: profileId,
      lock: doLock,
      speed,
      energy,
      emotion,
    });
    reload();
    reloadProject();
    if (doLock) router.push(`/projects/${project.id}/storyboard`);
  });

  if (loading && !data) return <LoadingBlock lines={6} />;
  if (!data) return <ErrorState error={error} onRetry={reload} />;

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
      <div className="space-y-4">
        <div>
          <h2 className="text-[18px] font-semibold text-ink">{t.voice.title}</h2>
          <p className="text-[13px] text-ink-muted">{t.voice.subtitle}</p>
        </div>

        <AIDirector notes={data.director_notes} compact />

        {data.profiles.length === 0 ? (
          <EmptyState title={t.voice.empty} />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {data.profiles.map((profile) => {
              const isActive = selectedId === profile.id;
              return (
                <div
                  key={profile.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => setActive(profile.id)}
                  onKeyDown={(event) => event.key === 'Enter' && setActive(profile.id)}
                  className={clsx(
                    'card card-hover cursor-pointer p-4 text-start transition',
                    isActive && 'border-accent shadow-focus',
                  )}
                >
                  <div className="mb-2 flex items-start justify-between">
                    <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-canvas text-ink-soft">
                      <Mic className="h-4 w-4" />
                    </span>
                    <div className="flex gap-1.5">
                      {profile.is_demo ? <Badge tone="neutral">{t.common.demo}</Badge> : null}
                      {isActive ? <Badge tone="accent">{t.common.selected}</Badge> : null}
                    </div>
                  </div>
                  <p className="text-[15px] font-semibold text-ink">
                    {locale === 'ar' ? profile.name_ar || profile.name : profile.name}
                  </p>
                  <p className="mt-0.5 text-[12px] text-ink-faint">
                    {profile.gender} · {profile.dialect.replace(/_/g, ' ')} · {profile.provider}
                  </p>
                  <Button
                    size="sm"
                    variant="secondary"
                    className="mt-3"
                    icon={<Play className="h-3.5 w-3.5" />}
                    loading={doPreview.pending}
                    onClick={(event) => {
                      event.stopPropagation();
                      setActive(profile.id);
                      void doPreview.run(profile.id);
                    }}
                  >
                    {t.common.preview}
                  </Button>
                </div>
              );
            })}
          </div>
        )}

        <Card>
          <CardTitle>{t.common.preview}</CardTitle>
          <p className="mb-3 rounded-xl bg-canvas px-3 py-2.5 text-[15px] leading-relaxed text-ink">
            {data.sample_text}
          </p>

          <div className="grid gap-4 sm:grid-cols-3">
            <Slider label={t.voice.speed} value={speed} min={0.7} max={1.4} step={0.05} onChange={setSpeed} />
            <Slider label={t.voice.energy} value={energy} onChange={setEnergy} />
            <Slider label={t.voice.emotion} value={emotion} onChange={setEmotion} />
          </div>

          {preview ? (
            <div className="mt-4 rounded-xl border border-line bg-raised p-3">
              <div className="mb-2 flex items-center justify-between text-[12.5px] text-ink-muted">
                <span className="flex items-center gap-1.5">
                  <Volume2 className="h-3.5 w-3.5" />
                  {t.common.duration}: <span className="ltr-nums">{timecode(preview.duration ?? 0)}</span>
                </span>
                <span className="ltr-nums">{money(preview.cost ?? 0)}</span>
              </div>
              {preview.url ? (
                <audio controls src={preview.url} className="w-full" />
              ) : (
                <p className="text-[12.5px] text-ink-faint">{t.errors.providerUnavailable}</p>
              )}
            </div>
          ) : null}

          <InlineError error={doPreview.error} />
        </Card>

        <div className="flex flex-wrap items-center justify-end gap-3">
          <InlineError error={lock.error} />
          {data.voice_locked ? <Badge tone="ok">{t.voice.voiceLocked}</Badge> : null}
          <Button
            variant="secondary"
            disabled={!selectedId}
            loading={lock.pending}
            onClick={() => selectedId && void lock.run(selectedId, false)}
          >
            {t.common.select}
          </Button>
          <Button
            size="lg"
            icon={<Lock className="h-4 w-4" />}
            disabled={!selectedId}
            loading={lock.pending}
            onClick={() => selectedId && void lock.run(selectedId, true)}
          >
            {t.voice.lockVoice}
          </Button>
        </div>
      </div>

      <aside className="space-y-4">
        <Card>
          <CardTitle>{t.script.timing}</CardTitle>
          <ul className="space-y-2">
            {data.timing.map((line) => (
              <li key={line.index} className="text-[12.5px]">
                <div className="flex items-center justify-between">
                  <span className="text-ink-faint">{line.role}</span>
                  <span className="ltr-nums text-ink-muted">
                    {timecode(line.start)} → {timecode(line.end)}
                  </span>
                </div>
                <p className="truncate text-ink-soft">{line.voice_line}</p>
              </li>
            ))}
          </ul>
        </Card>

        <Card>
          <CardTitle>{t.voice.pronunciation}</CardTitle>
          <dl className="space-y-2 text-[12.5px]">
            <PronRow label={t.wizard.name} written={data.pronunciation?.project_name?.written} spoken={data.pronunciation?.project_name?.spoken} />
            <PronRow label={t.brands.title} written={data.pronunciation?.brand_name?.written} spoken={data.pronunciation?.brand_name?.spoken} />
            <PronRow label={t.brands.contact} written={data.pronunciation?.phone?.written} spoken={data.pronunciation?.phone?.spoken} />
            {Object.entries(data.pronunciation?.numbers ?? {}).map(([written, spoken]) => (
              <PronRow key={written} label={written} written={written} spoken={String(spoken)} />
            ))}
          </dl>
        </Card>
      </aside>
    </div>
  );
}

function PronRow({ label, written, spoken }: { label: string; written?: string; spoken?: string }) {
  if (!written && !spoken) return null;
  return (
    <div className="rounded-lg bg-canvas px-2.5 py-2">
      <dt className="text-[11px] text-ink-faint">{label}</dt>
      <dd className="text-ink-soft">
        <span className="ltr-nums">{written || '—'}</span>
        {spoken ? <span className="text-ink-muted"> → {spoken}</span> : null}
      </dd>
    </div>
  );
}
