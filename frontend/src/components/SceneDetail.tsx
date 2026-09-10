'use client';

import { ChevronDown, Lock, LockOpen, RefreshCw, Sparkles, TrendingDown, TrendingUp } from 'lucide-react';
import { useState } from 'react';

import { useDirectorMode } from '@/components/AppShell';
import { Badge, Button, InlineError, Modal } from '@/components/ui';
import { useLocale } from '@/i18n/LocaleProvider';
import { mediaUrl } from '@/lib/api';
import type { Scene } from '@/lib/types';

const METHOD_TONE: Record<string, 'ok' | 'accent' | 'warn' | 'neutral' | 'gold'> = {
  original_video: 'ok',
  original_photo: 'ok',
  photo_motion: 'accent',
  motion_graphics: 'neutral',
  ai_image: 'warn',
  ai_video: 'gold',
};

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
}: {
  scene: Scene | null;
  open: boolean;
  onClose: () => void;
  onAction: (action: string, payload?: Record<string, unknown>) => void;
  pending?: boolean;
  error?: { code?: string; message: string; messageAr?: string } | null;
}) {
  const { t, locale, money, timecode, num } = useLocale();
  const { directorMode } = useDirectorMode();
  const [showPrompt, setShowPrompt] = useState(false);
  const [text, setText] = useState('');

  if (!scene) return null;
  const prompt = scene.compiled_prompt ?? {};

  return (
    <Modal
      open={open}
      onClose={onClose}
      wide
      title={`${t.storyboard.sceneDetails} ${scene.scene_number}`}
      footer={
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="secondary" icon={<TrendingDown className="h-3.5 w-3.5" />} disabled={pending} onClick={() => onAction('cheaper')}>
              {t.storyboard.makeCheaper}
            </Button>
            <Button size="sm" variant="secondary" icon={<TrendingUp className="h-3.5 w-3.5" />} disabled={pending} onClick={() => onAction('premium')}>
              {t.storyboard.makePremium}
            </Button>
            <Button size="sm" variant="secondary" icon={<RefreshCw className="h-3.5 w-3.5" />} disabled={pending} onClick={() => onAction('regenerate')}>
              {t.common.regenerate}
            </Button>
          </div>
          <Button
            size="sm"
            variant={scene.locked ? 'primary' : 'dark'}
            icon={scene.locked ? <LockOpen className="h-3.5 w-3.5" /> : <Lock className="h-3.5 w-3.5" />}
            disabled={pending}
            onClick={() => onAction('lock', { locked: !scene.locked })}
          >
            {scene.locked ? t.common.unlock : t.common.lock}
          </Button>
        </div>
      }
    >
      <div className="grid gap-5 sm:grid-cols-[200px_minmax(0,1fr)]">
        <div>
          <div className="overflow-hidden rounded-xl border border-line bg-graphite-900">
            {scene.output_url && scene.output_url.endsWith('.mp4') ? (
              <video src={mediaUrl(scene.output_url)} poster={mediaUrl(scene.thumbnail_url)} controls className="aspect-[9/16] w-full object-cover" />
            ) : (
              <img
                src={mediaUrl(scene.output_url || scene.thumbnail_url || scene.keyframe_url)}
                alt={`Scene ${scene.scene_number}`}
                className="aspect-[9/16] w-full object-cover"
              />
            )}
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <MethodBadge method={scene.production_method} />
            {scene.is_hook ? <Badge tone="accent">hook</Badge> : null}
            {scene.is_hero ? <Badge tone="gold">hero</Badge> : null}
            {scene.locked ? <Badge tone="ok">{t.common.locked}</Badge> : null}
          </div>
          <p className="ltr-nums mt-2 text-[12px] text-ink-faint">
            {timecode(scene.start_time)} → {timecode(scene.end_time)} · {money(scene.estimated_cost_usd)}
          </p>
          {scene.quality_score ? (
            <p className="ltr-nums mt-1 text-[12px] text-ink-muted">
              {t.common.score}: {num(scene.quality_score)}/100 · {num(scene.generation_attempts)} attempt(s)
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
            <p className="section-title mb-1.5">{t.common.edit}</p>
            <div className="flex gap-2">
              <input
                className="field"
                placeholder={t.script.onScreen}
                value={text}
                onChange={(event) => setText(event.target.value)}
              />
              <Button size="sm" disabled={!text || pending} onClick={() => onAction('update', { on_screen_text: text })}>
                {t.common.save}
              </Button>
            </div>
          </div>

          {directorMode ? (
            <div className="rounded-xl bg-graphite-900 p-3 text-[12px] text-slate-300">
              <button
                type="button"
                onClick={() => setShowPrompt((value) => !value)}
                className="mb-2 flex w-full items-center justify-between text-slate-200"
              >
                <span className="flex items-center gap-1.5">
                  <Sparkles className="h-3.5 w-3.5" />
                  {t.storyboard.prompt}
                </span>
                <ChevronDown className={`h-3.5 w-3.5 transition ${showPrompt ? 'rotate-180' : ''}`} />
              </button>
              <p className="ltr-nums">
                provider: {scene.recommended_provider} · model: {scene.recommended_model}
              </p>
              {prompt.routing_reason_ar ? <p className="mt-1 text-slate-400">{prompt.routing_reason_ar}</p> : null}
              {showPrompt ? (
                <pre className="ltr-nums mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-graphite-950 p-2.5 text-[11px] leading-relaxed text-slate-300">
                  {JSON.stringify(prompt, null, 2)}
                </pre>
              ) : null}
            </div>
          ) : null}

          <InlineError error={error ?? null} />
        </div>
      </div>
    </Modal>
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
