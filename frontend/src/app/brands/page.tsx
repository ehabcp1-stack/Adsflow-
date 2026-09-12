'use client';

import { Palette, Plus, Star, Trash2 } from 'lucide-react';
import { useState } from 'react';

import { PageHeader } from '@/components/AppShell';
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
  Toggle,
} from '@/components/ui';
import { useLocale } from '@/i18n/LocaleProvider';
import { api } from '@/lib/api';
import { useApi, useMutation } from '@/lib/hooks';
import type { BrandKit } from '@/lib/types';

const EMPTY: Partial<BrandKit> = {
  name: '',
  name_ar: '',
  primary_color: '#0F172A',
  secondary_color: '#2563EB',
  accent_color: '#C9A227',
  font_arabic: 'Cairo',
  font_latin: 'Inter',
  editing_style: 'luxury_clean',
  phone: '',
  website: '',
  preferred_phrases: [],
  forbidden_phrases: [],
  is_default: false,
};

export default function BrandsPage() {
  const { t, locale } = useLocale();
  const { data, error, loading, reload } = useApi<{ items: BrandKit[] }>('/brands');
  const [draft, setDraft] = useState<Partial<BrandKit> | null>(null);

  const save = useMutation(async (kit: Partial<BrandKit>) => {
    const body = {
      ...EMPTY,
      ...kit,
      caption_style: kit.caption_style ?? {},
      music_profile: kit.music_profile ?? {},
      cta_template: kit.cta_template ?? {},
      end_screen_template: kit.end_screen_template ?? {},
      social_handles: kit.social_handles ?? {},
      pronunciation_rules: kit.pronunciation_rules ?? {},
    };
    if (kit.id) await api.patch(`/brands/${kit.id}`, body);
    else await api.post('/brands', body);
    setDraft(null);
    reload();
  });

  const remove = useMutation(async (id: string) => {
    await api.delete(`/brands/${id}`);
    reload();
  });

  return (
    <>
      <PageHeader
        title={t.brands.title}
        subtitle={t.brands.subtitle}
        actions={
          <Button icon={<Plus className="h-4 w-4" />} onClick={() => setDraft({ ...EMPTY })}>
            {t.brands.newKit}
          </Button>
        }
      />

      {error ? <ErrorState error={error} onRetry={reload} /> : null}
      {loading && !data ? <LoadingBlock lines={4} /> : null}
      {/* Deleting a kit can fail (e.g. offline) — say so instead of nothing. */}
      <InlineError error={remove.error} />

      {data && data.items.length === 0 ? (
        <EmptyState
          title={t.brands.empty}
          icon={<Palette className="h-5 w-5" />}
          action={<Button onClick={() => setDraft({ ...EMPTY })}>{t.brands.newKit}</Button>}
        />
      ) : null}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {(data?.items ?? []).map((kit) => (
          <Card key={kit.id}>
            <CardTitle
              action={
                <div className="flex items-center gap-1.5">
                  {kit.is_default ? <Badge tone="accent" icon={<Star className="h-3 w-3" />}>{t.common.selected}</Badge> : null}
                  <button
                    type="button"
                    disabled={remove.pending}
                    onClick={() => void remove.run(kit.id)}
                    className="rounded-lg p-1.5 text-ink-faint transition hover:bg-canvas hover:text-danger disabled:cursor-not-allowed disabled:opacity-50"
                    aria-label={t.common.delete}
                    title={t.common.delete}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              }
            >
              {locale === 'ar' ? kit.name_ar || kit.name : kit.name}
            </CardTitle>

            <div className="mb-3 flex gap-2">
              {[kit.primary_color, kit.secondary_color, kit.accent_color].map((color) => (
                <span key={color} className="h-8 flex-1 rounded-lg border border-line" style={{ background: color }} />
              ))}
            </div>

            <dl className="space-y-1.5 text-[12.5px]">
              <Row label={t.brands.fonts} value={`${kit.font_arabic} · ${kit.font_latin}`} />
              <Row label={t.edit.style} value={kit.editing_style.replace(/_/g, ' ')} />
              <Row label={t.brands.contact} value={kit.phone ?? '—'} />
              <Row label="web" value={kit.website ?? '—'} />
              <Row label={t.brands.preferred} value={String(kit.preferred_phrases.length)} />
              <Row label={t.brands.forbidden} value={String(kit.forbidden_phrases.length)} />
            </dl>

            <Button variant="secondary" size="sm" full className="mt-4" onClick={() => setDraft(kit)}>
              {t.common.edit}
            </Button>
          </Card>
        ))}
      </div>

      <Modal
        open={Boolean(draft)}
        onClose={() => setDraft(null)}
        title={draft?.id ? t.common.edit : t.brands.newKit}
        wide
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setDraft(null)}>
              {t.common.cancel}
            </Button>
            <Button loading={save.pending} onClick={() => draft && void save.run(draft)}>
              {t.common.save}
            </Button>
          </div>
        }
      >
        {draft ? (
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={`${t.wizard.name} (EN)`} required>
              <input className="field" value={draft.name ?? ''} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            </Field>
            <Field label={`${t.wizard.name} (AR)`}>
              <input className="field" value={draft.name_ar ?? ''} onChange={(e) => setDraft({ ...draft, name_ar: e.target.value })} />
            </Field>
            {(['primary_color', 'secondary_color', 'accent_color'] as const).map((key) => (
              <Field key={key} label={key.replace(/_/g, ' ')}>
                <div className="flex gap-2">
                  <input
                    type="color"
                    className="h-10 w-12 rounded-lg border border-line"
                    value={String(draft[key] ?? '#000000')}
                    onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
                  />
                  <input
                    className="field ltr-nums"
                    value={String(draft[key] ?? '')}
                    onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
                  />
                </div>
              </Field>
            ))}
            <Field label={`${t.brands.fonts} (AR)`}>
              <input className="field" value={draft.font_arabic ?? ''} onChange={(e) => setDraft({ ...draft, font_arabic: e.target.value })} />
            </Field>
            <Field label={`${t.brands.fonts} (EN)`}>
              <input className="field" value={draft.font_latin ?? ''} onChange={(e) => setDraft({ ...draft, font_latin: e.target.value })} />
            </Field>
            <Field label={t.brands.contact}>
              <input className="field ltr-nums" value={draft.phone ?? ''} onChange={(e) => setDraft({ ...draft, phone: e.target.value })} />
            </Field>
            <Field label="website">
              <input className="field ltr-nums" value={draft.website ?? ''} onChange={(e) => setDraft({ ...draft, website: e.target.value })} />
            </Field>
            <Field label={t.brands.preferred} hint="comma separated">
              <input
                className="field"
                value={(draft.preferred_phrases ?? []).join('، ')}
                onChange={(e) => setDraft({ ...draft, preferred_phrases: e.target.value.split(/[،,]/).map((s) => s.trim()).filter(Boolean) })}
              />
            </Field>
            <Field label={t.brands.forbidden} hint="comma separated">
              <input
                className="field"
                value={(draft.forbidden_phrases ?? []).join('، ')}
                onChange={(e) => setDraft({ ...draft, forbidden_phrases: e.target.value.split(/[،,]/).map((s) => s.trim()).filter(Boolean) })}
              />
            </Field>
            <div className="sm:col-span-2">
              <Toggle checked={Boolean(draft.is_default)} onChange={(v) => setDraft({ ...draft, is_default: v })} label={t.common.selected} />
            </div>
            <div className="sm:col-span-2">
              <InlineError error={save.error} />
            </div>
          </div>
        ) : null}
      </Modal>
    </>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <dt className="text-ink-faint">{label}</dt>
      <dd className="ltr-nums truncate ps-2 text-ink-soft">{value}</dd>
    </div>
  );
}
