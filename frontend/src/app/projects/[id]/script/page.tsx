'use client';

import clsx from 'clsx';
import { Check, MessageSquareQuote, Pencil, Wand2 } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';

import { DirectorHint } from '@/components/AIDirector';
import { ProjectFrame } from '@/components/ProjectFrame';
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
  Tabs,
} from '@/components/ui';
import { useLocale } from '@/i18n/LocaleProvider';
import { api } from '@/lib/api';
import { useApi, useMutation } from '@/lib/hooks';
import type { ProjectDetail, ScriptLine, ScriptVersion } from '@/lib/types';

type ScriptPayload = {
  variants: ScriptVersion[];
  selected_script_id: string | null;
  actions: { key: string; label_en: string; label_ar: string }[];
  dialect_presets: { id: string; label_ar: string; label_en: string; tone_rules: string[] }[];
  state: string;
};

export default function ScriptPage() {
  return <ProjectFrame>{(project, reload) => <ScriptView project={project} reloadProject={reload} />}</ProjectFrame>;
}

function ScriptView({ project, reloadProject }: { project: ProjectDetail; reloadProject: () => void }) {
  const { t, locale, num, timecode } = useLocale();
  const router = useRouter();
  const { data, error, loading, reload } = useApi<ScriptPayload>(`/projects/${project.id}/script`);
  const [variant, setVariant] = useState<'primary' | 'more_sales' | 'more_emotional'>('primary');
  const [editing, setEditing] = useState(false);
  const [lines, setLines] = useState<ScriptLine[]>([]);
  const [ctaDraft, setCtaDraft] = useState('');

  const current = data?.variants.find((script) => script.variant === variant) ?? data?.variants[0] ?? null;

  useEffect(() => {
    if (current) setLines(current.lines);
  }, [current?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const generate = useMutation(async (regenerate = false) => {
    await api.post(`/projects/${project.id}/script/generate${regenerate ? '?regenerate=true' : ''}`);
    reload();
    reloadProject();
  });

  const refine = useMutation(async (action: string) => {
    if (!current) return;
    if (action === 'change_cta') {
      await api.post(`/projects/${project.id}/script/${current.id}/refine`, { action, new_cta: ctaDraft || project.cta });
    } else {
      await api.post(`/projects/${project.id}/script/${current.id}/refine`, { action });
    }
    reload();
    reloadProject();
  });

  const saveEdits = useMutation(async () => {
    if (!current) return;
    await api.patch(`/projects/${project.id}/script/${current.id}`, { lines });
    setEditing(false);
    reload();
    reloadProject();
  });

  const selectVariant = useMutation(async (id: string) => {
    await api.post(`/projects/${project.id}/script/select`, { id });
    reload();
    reloadProject();
  });

  const approve = useMutation(async () => {
    if (!current) return;
    await api.post(`/projects/${project.id}/script/approve`, { entity_id: current.id });
    reloadProject();
    router.push(`/projects/${project.id}/voice`);
  });

  if (loading && !data) return <LoadingBlock lines={6} />;

  if (!current) {
    return (
      <div className="space-y-4">
        {error ? <ErrorState error={error} onRetry={reload} /> : null}
        {generate.error ? <ErrorState error={generate.error} /> : null}
        <EmptyState
          title={t.script.empty}
          hint={t.concepts.subtitle}
          action={
            <Button loading={generate.pending} icon={<Wand2 className="h-4 w-4" />} onClick={() => void generate.run(false)}>
              {t.common.generate}
            </Button>
          }
        />
      </div>
    );
  }

  const preset = data?.dialect_presets.find((item) => item.id === current.dialect_preset);

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-[260px] flex-1">
            <Tabs
              value={variant}
              onChange={(value) => {
                setVariant(value);
                setEditing(false);
              }}
              tabs={[
                { value: 'primary' as const, label: t.script.primary },
                { value: 'more_sales' as const, label: t.script.more_sales },
                { value: 'more_emotional' as const, label: t.script.more_emotional },
              ]}
            />
          </div>
          <div className="flex gap-2">
            <Button size="sm" variant="secondary" loading={generate.pending} onClick={() => void generate.run(true)}>
              {t.common.regenerate}
            </Button>
            <Button
              size="sm"
              variant={editing ? 'primary' : 'secondary'}
              icon={<Pencil className="h-3.5 w-3.5" />}
              loading={saveEdits.pending}
              onClick={() => (editing ? void saveEdits.run() : setEditing(true))}
            >
              {editing ? t.common.save : t.common.edit}
            </Button>
          </div>
        </div>

        <Card>
          <CardTitle
            action={
              <div className="flex items-center gap-2">
                <Badge tone="neutral">
                  <span className="ltr-nums">{num(current.word_count)}</span> {t.script.words}
                </Badge>
                <Badge tone={current.score >= 88 ? 'ok' : 'warn'}>
                  <span className="ltr-nums">{num(current.score)}</span>/100
                </Badge>
                {current.is_selected ? <Badge tone="accent">{t.common.selected}</Badge> : null}
              </div>
            }
          >
            {t.script.voiceOver}
          </CardTitle>

          <ol className="space-y-3">
            {lines.map((line, index) => (
              <li
                key={line.index}
                className={clsx(
                  'rounded-xl border p-3',
                  line.role === 'hook' && 'border-accent/30 bg-accent-soft/40',
                  line.role === 'cta' && 'border-ok/25 bg-ok/[0.05]',
                  line.role === 'body' && 'border-line bg-raised',
                )}
              >
                <div className="mb-1.5 flex items-center justify-between">
                  <Badge tone={line.role === 'hook' ? 'accent' : line.role === 'cta' ? 'ok' : 'neutral'}>
                    {line.role}
                  </Badge>
                  <span className="ltr-nums text-[11.5px] text-ink-faint">
                    {timecode(line.start)} → {timecode(line.end)}
                  </span>
                </div>

                {editing ? (
                  <textarea
                    className="field min-h-[64px] resize-y text-[15px]"
                    value={line.voice_line}
                    onChange={(event) => {
                      const next = [...lines];
                      next[index] = { ...line, voice_line: event.target.value };
                      setLines(next);
                    }}
                  />
                ) : (
                  <p className="text-[16px] leading-relaxed text-ink">{line.voice_line}</p>
                )}

                <p className="mt-2 flex items-center gap-1.5 text-[12.5px] text-ink-muted">
                  <MessageSquareQuote className="h-3.5 w-3.5" />
                  {t.script.onScreen}: <span className="font-medium text-ink-soft">{line.on_screen_text}</span>
                </p>
              </li>
            ))}
          </ol>

          <InlineError error={saveEdits.error} />
        </Card>

        <Card>
          <CardTitle>{t.common.refine}</CardTitle>
          <div className="flex flex-wrap gap-2">
            {(data?.actions ?? []).map((action) => (
              <Button
                key={action.key}
                size="sm"
                variant="secondary"
                loading={refine.pending}
                onClick={() => void refine.run(action.key)}
              >
                {locale === 'ar' ? action.label_ar : action.label_en}
              </Button>
            ))}
          </div>
          {/* This field feeds the "change CTA" refine action above — say so
              rather than leaving an input with no visible purpose. */}
          <div className="mt-3">
            <Field label={t.wizard.cta} hint={t.common.refine}>
              <input
                className="field"
                placeholder={project.cta || t.wizard.ctaPlaceholder}
                value={ctaDraft}
                onChange={(event) => setCtaDraft(event.target.value)}
              />
            </Field>
          </div>
          <InlineError error={refine.error} />
        </Card>

        <div className="flex flex-wrap items-center justify-end gap-3">
          {!current.is_selected ? (
            <Button variant="secondary" loading={selectVariant.pending} onClick={() => void selectVariant.run(current.id)}>
              {t.common.select}
            </Button>
          ) : null}
          <InlineError error={approve.error} />
          <Button size="lg" icon={<Check className="h-4 w-4" />} loading={approve.pending} onClick={() => void approve.run()}>
            {t.script.approve}
          </Button>
        </div>
      </div>

      <aside className="space-y-4">
        <Card>
          <CardTitle>{t.wizard.dialect}</CardTitle>
          <p className="text-[14px] font-medium text-ink">
            {locale === 'ar' ? preset?.label_ar : preset?.label_en}
          </p>
          <ul className="mt-2 space-y-1.5 text-[12.5px] text-ink-muted">
            {(preset?.tone_rules ?? []).map((rule) => (
              <li key={rule}>· {rule}</li>
            ))}
          </ul>
        </Card>

        <Card>
          <CardTitle>{t.script.critic}</CardTitle>
          <ul className="space-y-2 text-[13px] text-ink-soft">
            {current.critic_notes.map((note, index) => (
              <li key={index}>· {note}</li>
            ))}
          </ul>
        </Card>

        <DirectorHint
          ar="النص المنطوق يختلف عن المكتوب — الكابشن يبقى قصير وواضح."
          en="Spoken lines differ from on-screen copy — captions stay short and readable."
        />
      </aside>
    </div>
  );
}
