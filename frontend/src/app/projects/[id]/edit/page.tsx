'use client';

import clsx from 'clsx';
import { Film, Layers, Play, Settings2, Sparkles } from 'lucide-react';
import { useRouter } from 'next/navigation';

import { AIDirector } from '@/components/AIDirector';
import { useDirectorMode } from '@/components/AppShell';
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
  Toggle,
} from '@/components/ui';
import { useLocale } from '@/i18n/LocaleProvider';
import { api, mediaUrl } from '@/lib/api';
import { useApi, useMutation } from '@/lib/hooks';
import type { DirectorNote, EditingStyleOption, ProjectDetail, Render, Scene } from '@/lib/types';

type EditPayload = {
  render: Render | null;
  styles: EditingStyleOption[];
  caption_templates: { key: string; label_en: string; label_ar: string }[];
  remix_operations: { key: string; label_en: string; label_ar: string }[];
  settings: Record<string, any>;
  editing_style: string;
  recommended_style: string;
  scenes: Scene[];
  director_notes: DirectorNote[];
  state: string;
};

export default function EditPage() {
  return <ProjectFrame>{(project, reload) => <EditView project={project} reloadProject={reload} />}</ProjectFrame>;
}

function EditView({ project, reloadProject }: { project: ProjectDetail; reloadProject: () => void }) {
  const { t, locale, num } = useLocale();
  const router = useRouter();
  const { directorMode } = useDirectorMode();
  const { data, error, loading, reload } = useApi<EditPayload>(`/projects/${project.id}/edit`);

  const update = useMutation(async (changes: Record<string, unknown>) => {
    await api.post(`/projects/${project.id}/edit/settings`, { changes });
    reload();
  });

  const render = useMutation(async () => {
    await api.post(`/projects/${project.id}/edit/render`);
    reload();
    reloadProject();
  });

  const toQC = useMutation(async () => {
    await api.post(`/projects/${project.id}/qc/run`);
    reloadProject();
    router.push(`/projects/${project.id}/qc`);
  });

  if (loading && !data) return <LoadingBlock lines={6} />;
  if (!data) return <ErrorState error={error} onRetry={reload} />;

  const settings = data.settings ?? {};
  const captionTrack = data.render?.timeline.find((track) => track.type === 'captions');

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
      {/* Center: large preview */}
      <div className="space-y-4">
        <div className="workspace p-4">
          <div className="mb-3 flex items-center justify-between">
            <span className="flex items-center gap-2 text-[13px] font-semibold text-slate-200">
              <Film className="h-4 w-4" />
              {t.edit.preview}
            </span>
            <div className="flex items-center gap-2">
              {data.render ? (
                <Badge tone="dark">
                  <span className="ltr-nums">
                    v{num(data.render.version)} · {data.render.width}×{data.render.height}
                  </span>
                </Badge>
              ) : null}
              <Button size="sm" variant="dark" loading={render.pending} icon={<Sparkles className="h-3.5 w-3.5" />} onClick={() => void render.run()}>
                {render.pending ? t.edit.rendering : t.edit.render}
              </Button>
            </div>
          </div>

          <div className="mx-auto w-full max-w-[300px]">
            <div className="relative aspect-[9/16] overflow-hidden rounded-xl bg-graphite-950">
              {data.render?.url && data.render.url.endsWith('.mp4') ? (
                <video
                  key={data.render.url}
                  src={mediaUrl(data.render.url)}
                  poster={mediaUrl(data.render.poster_url)}
                  controls
                  className="h-full w-full object-cover"
                />
              ) : data.render?.poster_url ? (
                <img src={mediaUrl(data.render.poster_url)} alt="" className="h-full w-full object-cover" />
              ) : (
                <div className="flex h-full items-center justify-center text-slate-600">
                  <Play className="h-8 w-8" />
                </div>
              )}

              {/* Live Arabic caption overlay preview (rendered by our editor, never by the model) */}
              {settings.captions_enabled && captionTrack?.clips?.[0] ? (
                <div className="pointer-events-none absolute inset-x-4 bottom-[18%]">
                  <p
                    dir="rtl"
                    className="rounded-lg bg-black/60 px-3 py-2 text-center text-[13px] font-semibold leading-snug text-white"
                    style={{ fontFamily: 'var(--font-arabic)' }}
                  >
                    {captionTrack.clips[0].text}
                  </p>
                </div>
              ) : null}

              {settings.branding_enabled ? (
                <span className="absolute start-3 top-3 rounded-md bg-white/90 px-2 py-1 text-[10px] font-bold text-ink">
                  TADAFQ
                </span>
              ) : null}
            </div>
          </div>

          {/* Simple timeline */}
          {data.scenes.length > 0 ? (
            <div className="mt-4">
              <p className="mb-2 text-[12px] text-slate-400">{t.storyboard.timeline}</p>
              <div className="flex gap-1">
                {data.scenes.map((scene) => (
                  <div
                    key={scene.id}
                    style={{ flexGrow: scene.duration_sec }}
                    className="h-10 overflow-hidden rounded border border-graphite-line"
                    title={`${scene.scene_number}. ${scene.purpose}`}
                  >
                    <img src={mediaUrl(scene.thumbnail_url)} alt="" className="h-full w-full object-cover opacity-85" />
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>

        {data.render ? (
          <Card>
            <CardTitle
              action={
                <Badge tone="neutral">
                  <span className="ltr-nums">{num(data.render.timeline.length)}</span> {t.edit.tracks}
                </Badge>
              }
            >
              {t.edit.tracks}
            </CardTitle>
            <ul className="space-y-2">
              {data.render.timeline.map((track) => (
                <li key={track.type} className="flex items-center justify-between rounded-xl border border-line bg-raised px-3 py-2">
                  <span className="flex items-center gap-2 text-[13px] font-medium text-ink">
                    <Layers className="h-3.5 w-3.5 text-ink-faint" />
                    {track.type}
                  </span>
                  <span className="text-[12px] text-ink-muted">
                    {track.clips ? (
                      <>
                        <span className="ltr-nums">{num(track.clips.length)}</span> {t.edit.clips}
                      </>
                    ) : track.url ? (
                      t.edit.audio
                    ) : (
                      '—'
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </Card>
        ) : (
          <EmptyState title={t.edit.empty} action={<Button loading={render.pending} onClick={() => void render.run()}>{t.edit.render}</Button>} />
        )}

        <div className="flex items-center justify-end gap-3">
          <InlineError error={toQC.error ?? render.error} />
          <Button size="lg" loading={toQC.pending} onClick={() => void toQC.run()}>
            {t.qc.run}
          </Button>
        </div>
      </div>

      {/* Right: simple controls (advanced hidden behind Director Mode) */}
      <aside className="space-y-4">
        <AIDirector notes={data.director_notes} compact />

        <Card>
          <CardTitle>{t.edit.style}</CardTitle>
          <div className="space-y-2">
            {data.styles.map((style) => (
              <button
                key={style.key}
                type="button"
                onClick={() => void update.run({ editing_style: style.key })}
                className={clsx(
                  'w-full rounded-xl border px-3 py-2.5 text-start transition',
                  data.editing_style === style.key ? 'border-accent bg-accent-soft' : 'border-line hover:border-line-strong',
                )}
              >
                <span className="flex items-center justify-between">
                  <span className="text-[13.5px] font-medium text-ink">
                    {locale === 'ar' ? style.label_ar : style.label_en}
                  </span>
                  {data.recommended_style === style.key ? <Badge tone="accent">{t.common.recommended}</Badge> : null}
                </span>
                <span className="ltr-nums mt-0.5 block text-[11.5px] text-ink-faint">
                  cut {style.cut_pace_sec}s · {style.transition} · captions {style.caption_density}
                </span>
              </button>
            ))}
          </div>
        </Card>

        <Card>
          <CardTitle>{t.edit.title}</CardTitle>
          <div className="space-y-3.5">
            <Toggle checked={Boolean(settings.captions_enabled)} onChange={(v) => void update.run({ captions_enabled: v })} label={t.edit.captions} />
            <Toggle checked={Boolean(settings.music_enabled)} onChange={(v) => void update.run({ music_enabled: v })} label={t.edit.music} />
            <Toggle checked={Boolean(settings.branding_enabled)} onChange={(v) => void update.run({ branding_enabled: v })} label={t.edit.branding} />
            <Toggle checked={Boolean(settings.cta_enabled)} onChange={(v) => void update.run({ cta_enabled: v })} label={t.edit.cta} />
            <Toggle checked={Boolean(settings.end_screen_enabled)} onChange={(v) => void update.run({ end_screen_enabled: v })} label={t.edit.endScreen} />
            <Slider
              label={t.edit.musicVolume}
              value={Number(settings.music_volume ?? 0.22)}
              onChange={(value) => void update.run({ music_volume: value })}
              format={(value) => `${Math.round(value * 100)}%`}
            />
          </div>
        </Card>

        {directorMode ? (
          <Card>
            <CardTitle>
              <span className="flex items-center gap-1.5">
                <Settings2 className="h-3.5 w-3.5" />
                {t.common.directorMode}
              </span>
            </CardTitle>
            <div className="space-y-3.5">
              <Toggle checked={Boolean(settings.sfx_enabled)} onChange={(v) => void update.run({ sfx_enabled: v })} label={t.edit.sfx} />
              <Toggle
                checked={Boolean(settings.duck_music_under_voice)}
                onChange={(v) => void update.run({ duck_music_under_voice: v })}
                label={t.edit.ducking}
              />
              <Slider
                label={t.edit.voiceVolume}
                value={Number(settings.voice_volume ?? 1)}
                onChange={(value) => void update.run({ voice_volume: value })}
                format={(value) => `${Math.round(value * 100)}%`}
              />
              <div>
                <p className="label">{t.edit.captions}</p>
                <div className="flex flex-wrap gap-2">
                  {data.caption_templates.map((template) => (
                    <button
                      key={template.key}
                      type="button"
                      onClick={() => void update.run({ caption_template: template.key })}
                      className={clsx(
                        'rounded-lg border px-2.5 py-1 text-[12px]',
                        settings.caption_template === template.key ? 'border-accent bg-accent-soft text-accent-dark' : 'border-line text-ink-soft',
                      )}
                    >
                      {locale === 'ar' ? template.label_ar : template.label_en}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </Card>
        ) : null}
      </aside>
    </div>
  );
}
