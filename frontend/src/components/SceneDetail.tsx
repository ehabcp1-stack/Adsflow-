'use client';

import clsx from 'clsx';
import { ChevronDown, Lock, LockOpen, RefreshCw, Sparkles, TrendingDown, TrendingUp } from 'lucide-react';
import { useEffect, useState } from 'react';

import { useDirectorMode } from '@/components/AppShell';
import { Badge, Button, InlineError, Modal } from '@/components/ui';
import { useLocale } from '@/i18n/LocaleProvider';
import { mediaUrl } from '@/lib/api';
import { useApi } from '@/lib/hooks';
import type { Scene, SystemModel, SystemProviders } from '@/lib/types';

const METHOD_TONE: Record<string, 'ok' | 'accent' | 'warn' | 'neutral' | 'gold'> = {
  original_video: 'ok',
  original_photo: 'ok',
  photo_motion: 'accent',
  motion_graphics: 'neutral',
  ai_image: 'warn',
  ai_video: 'gold',
};

/** Timeline/legend colours, one per production method. */
export const METHOD_COLOR: Record<string, string> = {
  original_video: '#0E9F6E',
  original_photo: '#0E9F6E',
  photo_motion: '#2563EB',
  motion_graphics: '#667085',
  ai_image: '#D97706',
  ai_video: '#C9A227',
};

/** Methods produced locally never touch a provider, so they have no model. */
const LOCAL_METHODS = new Set(['original_video', 'original_photo', 'photo_motion', 'motion_graphics']);

/** Which provider catalogue a scene's method buys from. */
function kindForMethod(method: string): 'video' | 'image' | null {
  if (method === 'ai_video') return 'video';
  if (method === 'ai_image') return 'image';
  return null;
}

export function MethodBadge({ method }: { method: string }) {
  return <Badge tone={METHOD_TONE[method] ?? 'neutral'}>{method.replace(/_/g, ' ')}</Badge>;
}

/** Detailed scene panel — opens when a storyboard scene is clicked. */
export function SceneDetail({
  scene,
  open,
  onClose,
  onAction,
  pending,
  error,
  promptVersion,
}: {
  scene: Scene | null;
  open: boolean;
  onClose: () => void;
  onAction: (action: string, payload?: Record<string, unknown>) => void;
  pending?: boolean;
  error?: { code?: string; message: string; messageAr?: string } | null;
  /** Storyboard version the compiled prompt belongs to. */
  promptVersion?: number;
}) {
  const { t, money, timecode, num } = useLocale();
  const { directorMode } = useDirectorMode();
  const [text, setText] = useState('');

  useEffect(() => {
    setText(scene?.on_screen_text ?? '');
  }, [scene?.id, scene?.on_screen_text]);

  if (!scene) return null;
  const locked = scene.locked;

  return (
    <Modal
      open={open}
      onClose={onClose}
      wide
      title={`${t.storyboard.sceneDetails} ${scene.scene_number}`}
      footer={
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap gap-2">
            {/* Locked scenes never regenerate — the control says so instead of failing. */}
            <Button
              size="sm"
              variant="secondary"
              icon={<TrendingDown className="h-3.5 w-3.5" />}
              disabled={pending || locked}
              title={locked ? t.errors.sceneLocked : undefined}
              onClick={() => onAction('cheaper')}
            >
              {t.storyboard.makeCheaper}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              icon={<TrendingUp className="h-3.5 w-3.5" />}
              disabled={pending || locked}
              title={locked ? t.errors.sceneLocked : undefined}
              onClick={() => onAction('premium')}
            >
              {t.storyboard.makePremium}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              icon={<RefreshCw className="h-3.5 w-3.5" />}
              disabled={pending || locked}
              title={locked ? t.errors.sceneLocked : undefined}
              onClick={() => onAction('regenerate')}
            >
              {t.common.regenerate}
            </Button>
          </div>
          <Button
            size="sm"
            variant={locked ? 'primary' : 'dark'}
            icon={locked ? <LockOpen className="h-3.5 w-3.5" /> : <Lock className="h-3.5 w-3.5" />}
            disabled={pending}
            onClick={() => onAction('lock', { locked: !locked })}
          >
            {locked ? t.common.unlock : t.common.lock}
          </Button>
        </div>
      }
    >
      <div className="grid gap-5 sm:grid-cols-[200px_minmax(0,1fr)]">
        <div>
          <div className="overflow-hidden rounded-xl border border-line bg-graphite-900">
            {scene.output_url && scene.output_url.endsWith('.mp4') ? (
              <video
                src={mediaUrl(scene.output_url)}
                poster={mediaUrl(scene.thumbnail_url)}
                controls
                className="aspect-[9/16] w-full object-cover"
              />
            ) : (
              <img
                src={mediaUrl(scene.output_url || scene.thumbnail_url || scene.keyframe_url)}
                alt={`${t.storyboard.title} ${scene.scene_number}`}
                className="aspect-[9/16] w-full object-cover"
              />
            )}
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <MethodBadge method={scene.production_method} />
            {scene.is_hook ? <Badge tone="accent">hook</Badge> : null}
            {scene.is_hero ? <Badge tone="gold">hero</Badge> : null}
            {locked ? <Badge tone="ok">{t.common.locked}</Badge> : null}
          </div>
          <p className="ltr-nums mt-2 text-[12px] text-ink-faint">
            {timecode(scene.start_time)} → {timecode(scene.end_time)} · {money(scene.estimated_cost_usd)}
          </p>
          {scene.quality_score ? (
            <p className="ltr-nums mt-1 text-[12px] text-ink-muted">
              {t.common.score}: {num(scene.quality_score)}/100
            </p>
          ) : null}
        </div>

        <div className="space-y-3 text-[13.5px]">
          <Row label={t.storyboard.purpose} value={scene.purpose} />
          <Row label={t.script.voiceOver} value={scene.voice_line} strong />
          <Row label={t.script.onScreen} value={scene.on_screen_text} />
          <Row label={t.storyboard.visualDirection} value={scene.visual_direction} />
          <div className="grid grid-cols-2 gap-3">
            <Row label={t.storyboard.camera} value={scene.camera_direction} />
            <Row label={t.storyboard.movement} value={scene.camera_movement} />
            <Row label={t.storyboard.lighting} value={scene.lighting} />
            <Row label={t.storyboard.transition} value={scene.transition} />
            <Row label={t.edit.music} value={scene.music_instruction} />
            <Row label={t.edit.sfx} value={scene.sfx_instruction} />
          </div>

          <div className="rounded-xl border border-line bg-raised p-3">
            <p className="section-title mb-1.5">{t.script.onScreen}</p>
            <div className="flex gap-2">
              <input
                className="field"
                placeholder={t.script.onScreen}
                value={text}
                onChange={(event) => setText(event.target.value)}
                disabled={locked}
              />
              <Button
                size="sm"
                disabled={locked || pending || !text || text === scene.on_screen_text}
                title={locked ? t.errors.sceneLocked : undefined}
                onClick={() => onAction('update', { on_screen_text: text })}
              >
                {t.common.save}
              </Button>
            </div>
            {locked ? <p className="mt-1.5 text-[12px] text-ink-faint">{t.errors.sceneLocked}</p> : null}
          </div>

          {directorMode ? (
            <DirectorPanel scene={scene} onAction={onAction} pending={pending} promptVersion={promptVersion} />
          ) : (
            <p className="flex items-center gap-2 rounded-xl bg-accent-soft/60 px-3 py-2 text-[12.5px] text-accent-dark">
              <Sparkles className="h-3.5 w-3.5 shrink-0" />
              {t.director.autoSmart} — {t.director.autoSmartHint}
            </p>
          )}

          <InlineError error={error ?? null} />
        </div>
      </div>
    </Modal>
  );
}

/* -------------------------------------------------------- Director Mode */
/**
 * Everything the director decided for this scene, and the one manual lever
 * that changes it. Hidden entirely unless Director Mode is on — normal users
 * only ever see "Auto Smart" (CLAUDE.md §9).
 */
function DirectorPanel({
  scene,
  onAction,
  pending,
  promptVersion,
}: {
  scene: Scene;
  onAction: (action: string, payload?: Record<string, unknown>) => void;
  pending?: boolean;
  promptVersion?: number;
}) {
  const { t, locale, money, num } = useLocale();
  const [showPrompt, setShowPrompt] = useState(false);
  const [override, setOverride] = useState('');

  const prompt: Record<string, any> = scene.compiled_prompt ?? {};
  const routing: Record<string, any> = prompt.routing ?? {};
  const kind = kindForMethod(scene.production_method);
  const isLocal = LOCAL_METHODS.has(scene.production_method);

  // Only fetch the catalogue when it can actually be used for an override.
  const catalogue = useApi<SystemProviders>('/system/providers', { enabled: Boolean(kind) });
  const models: SystemModel[] = kind ? catalogue.data?.by_kind[kind] ?? [] : [];
  const selectable = models.filter((model) => model.enabled);

  const current = `${scene.recommended_provider}:${scene.recommended_model}`;
  useEffect(() => setOverride(current), [current]);

  // The router records the candidates it compared; when it did not (non-hook,
  // non-hero scenes), fall back to the catalogue's own fallback order.
  const compared: [string, string][] = Array.isArray(routing.compare_candidates) ? routing.compare_candidates : [];
  const chain: string[] = compared.length
    ? compared.map(([provider, model]) => `${provider} · ${model}`)
    : selectable.map((model) => `${model.provider} · ${model.model_id}`);

  const references: string[] = Array.isArray(prompt.references) ? prompt.references : [];
  const reason = locale === 'ar' ? prompt.routing_reason_ar || routing.reason_ar : routing.reason_en;
  const changed = override !== current;

  return (
    <div className="space-y-3 rounded-xl bg-graphite-900 p-3.5 text-[12px] text-slate-300">
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1.5 text-[12.5px] font-semibold text-slate-100">
          <Sparkles className="h-3.5 w-3.5" />
          {t.director.panel}
        </span>
        {routing.downgraded ? <Badge tone="warn">{t.director.downgraded}</Badge> : null}
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">
        <Meta label={t.common.provider} value={scene.recommended_provider || '—'} />
        <Meta label={t.common.model} value={scene.recommended_model || '—'} />
        <Meta label={t.storyboard.method} value={scene.production_method.replace(/_/g, ' ')} />
        <Meta label={t.director.estimatedCost} value={money(scene.estimated_cost_usd)} />
        <Meta
          label={t.director.actualCost}
          value={scene.actual_cost_usd > 0 ? money(scene.actual_cost_usd) : t.director.notGeneratedYet}
        />
        <Meta label={t.director.retries} value={num(scene.generation_attempts)} />
        <Meta
          label={t.director.quality}
          value={scene.quality_score ? `${num(Math.round(scene.quality_score))}/100` : '—'}
        />
        <Meta label={t.director.promptVersion} value={promptVersion ? `v${num(promptVersion)}` : '—'} />
        <Meta label={t.common.status} value={scene.status.replace(/_/g, ' ')} />
      </dl>

      {reason ? <p className="text-slate-400">{reason}</p> : null}

      {/* Fallback chain */}
      <div>
        <p className="mb-1 text-[11px] uppercase tracking-wider text-slate-500">{t.director.fallback}</p>
        {chain.length === 0 ? (
          <p className="text-slate-400">{isLocal ? t.director.autoSmartHint : t.director.noFallback}</p>
        ) : (
          <ol className="ltr-nums flex flex-wrap items-center gap-1.5">
            {chain.map((step, index) => (
              <li
                key={step}
                className={clsx(
                  'rounded-md px-2 py-0.5 text-[11px]',
                  index === 0 ? 'bg-slate-100/15 text-slate-100' : 'bg-slate-100/5 text-slate-400',
                )}
              >
                {index + 1}. {step}
              </li>
            ))}
          </ol>
        )}
      </div>

      {/* Input references */}
      <div>
        <p className="mb-1 text-[11px] uppercase tracking-wider text-slate-500">{t.director.references}</p>
        {references.length === 0 && !scene.selected_asset_id ? (
          <p className="text-slate-400">{t.director.noReferences}</p>
        ) : (
          <ul className="ltr-nums space-y-0.5 text-[11px] text-slate-400">
            {scene.selected_asset_id ? <li className="truncate">asset: {scene.selected_asset_id}</li> : null}
            {references.map((reference) => (
              <li key={reference} className="truncate">
                {reference}
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Manual override — a real PATCH, or a visibly disabled control. */}
      <div className="border-t border-graphite-line pt-3">
        <p className="mb-1 text-[11px] uppercase tracking-wider text-slate-500">{t.director.override}</p>
        {!kind ? (
          <p className="text-slate-400">{t.director.autoSmartHint}</p>
        ) : (
          <>
            <div className="flex flex-wrap gap-2">
              <select
                value={override}
                disabled={scene.locked || pending || selectable.length === 0}
                onChange={(event) => setOverride(event.target.value)}
                className="ltr-nums min-w-0 flex-1 rounded-lg border border-graphite-line bg-graphite-800 px-2.5 py-1.5 text-[12px] text-slate-100 disabled:opacity-50"
              >
                {selectable.some((model) => `${model.provider}:${model.model_id}` === current) ? null : (
                  <option value={current}>{current.replace(':', ' · ')}</option>
                )}
                {selectable.map((model) => (
                  <option key={`${model.provider}:${model.model_id}`} value={`${model.provider}:${model.model_id}`}>
                    {model.provider} · {model.model_id}
                    {model.is_mock ? ` (${t.common.mock})` : ''}
                  </option>
                ))}
              </select>
              <Button
                size="sm"
                variant="dark"
                disabled={scene.locked || pending || !changed}
                title={scene.locked ? t.director.overrideLocked : undefined}
                onClick={() => {
                  const [provider, model] = override.split(':');
                  onAction('update', { recommended_provider: provider, recommended_model: model });
                }}
              >
                {t.director.applyOverride}
              </Button>
            </div>
            <p className="mt-1.5 text-[11px] text-slate-500">
              {scene.locked ? t.director.overrideLocked : t.director.overrideHint}
            </p>
          </>
        )}
      </div>

      {/* Compiled prompt — never the raw script (CLAUDE.md §6). */}
      <div className="border-t border-graphite-line pt-3">
        <button
          type="button"
          onClick={() => setShowPrompt((value) => !value)}
          className="flex w-full items-center justify-between text-[12.5px] text-slate-200"
        >
          <span>
            {t.storyboard.prompt}
            {promptVersion ? <span className="ltr-nums ms-1.5 text-slate-500">v{num(promptVersion)}</span> : null}
          </span>
          <span className="flex items-center gap-1.5 text-[11px] text-slate-500">
            {showPrompt ? t.common.hide : t.common.show}
            <ChevronDown className={clsx('h-3.5 w-3.5 transition', showPrompt && 'rotate-180')} />
          </span>
        </button>
        {showPrompt ? (
          <pre className="ltr-nums mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-graphite-950 p-2.5 text-[11px] leading-relaxed text-slate-300">
            {JSON.stringify(prompt, null, 2)}
          </pre>
        ) : null}
      </div>
    </div>
  );
}

function Meta({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="truncate text-[10.5px] uppercase tracking-wider text-slate-500">{label}</dt>
      <dd className="ltr-nums truncate text-[12px] font-medium text-slate-200">{value}</dd>
    </div>
  );
}

function Row({ label, value, strong }: { label: string; value?: string; strong?: boolean }) {
  if (!value) return null;
  return (
    <div>
      <p className="text-[11.5px] text-ink-faint">{label}</p>
      <p className={strong ? 'text-[15px] font-medium leading-relaxed text-ink' : 'text-ink-soft'}>{value}</p>
    </div>
  );
}
