'use client';

import { ArrowLeft, ArrowRight, Check, Sparkles } from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useMemo, useState } from 'react';

import { AIDirector } from '@/components/AIDirector';
import { PageHeader } from '@/components/AppShell';
import { AssetUploader } from '@/components/AssetUploader';
import {
  Button,
  Card,
  ErrorState,
  Field,
  InlineError,
  LoadingBlock,
  Segmented,
  Toggle,
} from '@/components/ui';
import { useLocale } from '@/i18n/LocaleProvider';
import { api } from '@/lib/api';
import { useApi, useMutation } from '@/lib/hooks';
import type { Asset, BrandKit, MetaOptions, Option, ProjectDetail } from '@/lib/types';

type Draft = {
  name: string;
  category: string;
  goal: string;
  platform: string;
  duration_sec: number;
  language: string;
  dialect: string;
  tone: string;
  target_audience: string;
  key_information: string;
  cta: string;
  production_mode: string;
  voice_over_enabled: boolean;
  brand_kit_id: string | null;
};

const STEP_KEYS = ['basics', 'audience', 'assets', 'review'] as const;
type StepKey = (typeof STEP_KEYS)[number];

function NewProjectWizard() {
  const { t, locale, num, isRTL } = useLocale();
  const router = useRouter();
  const params = useSearchParams();
  const Next = isRTL ? ArrowLeft : ArrowRight;
  const Prev = isRTL ? ArrowRight : ArrowLeft;

  const { data: options, error: optionsError, loading, reload } = useApi<MetaOptions>('/meta/options');
  const { data: brands } = useApi<{ items: BrandKit[] }>('/brands');

  const [step, setStep] = useState(0);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [draft, setDraft] = useState<Draft>({
    name: '',
    category: 'real_estate',
    goal: 'leads',
    platform: 'instagram_reels',
    duration_sec: 30,
    language: 'iraqi_arabic',
    dialect: 'iraqi_professional',
    tone: 'ai_decide',
    target_audience: '',
    key_information: '',
    cta: '',
    production_mode: params.get('mode') ?? 'auto_smart',
    voice_over_enabled: true,
    brand_kit_id: null,
  });

  const label = (option: Option) => (locale === 'ar' ? option.label_ar : option.label_en);
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft((current) => ({ ...current, [key]: value }));

  const create = useMutation(async () => {
    const project = await api.post<ProjectDetail>('/projects', {
      ...draft,
      brand_kit_id: draft.brand_kit_id ?? undefined,
      asset_ids: assets.map((asset) => asset.id),
    });
    router.push(`/projects/${project.id}/analysis`);
    return project;
  });

  const canContinue = useMemo(() => {
    if (step === 0) return draft.name.trim().length > 1;
    return true;
  }, [step, draft.name]);

  if (loading && !options) {
    return (
      <Card>
        <LoadingBlock lines={6} />
      </Card>
    );
  }
  if (optionsError) return <ErrorState error={optionsError} onRetry={reload} />;
  if (!options) return null;

  const stepKey: StepKey = STEP_KEYS[step];

  return (
    <>
      <PageHeader
        title={t.wizard.title}
        subtitle={`${t.wizard.step} ${num(step + 1)} ${t.wizard.of} ${num(STEP_KEYS.length)} · ${t.wizard[stepKey]}`}
      />

      {/* Step rail */}
      <ol className="mb-6 flex flex-wrap gap-2">
        {STEP_KEYS.map((key, index) => (
          <li key={key}>
            <button
              type="button"
              onClick={() => index <= step && setStep(index)}
              className={`flex items-center gap-2 rounded-xl px-3 py-1.5 text-[13px] font-medium transition ${
                index === step
                  ? 'bg-ink text-white'
                  : index < step
                    ? 'bg-ok/10 text-ok'
                    : 'bg-surface text-ink-faint border border-line'
              }`}
            >
              <span className="ltr-nums flex h-4.5 w-4.5 items-center justify-center text-[11px]">
                {index < step ? <Check className="h-3 w-3" /> : index + 1}
              </span>
              {t.wizard[key]}
            </button>
          </li>
        ))}
      </ol>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_300px]">
        <Card className="space-y-5">
          {stepKey === 'basics' ? (
            <>
              <Field label={t.wizard.name} required>
                <input
                  className="field"
                  value={draft.name}
                  autoFocus
                  placeholder={t.wizard.namePlaceholder}
                  onChange={(event) => set('name', event.target.value)}
                />
              </Field>

              <Field label={t.wizard.category}>
                <Segmented
                  size="sm"
                  value={draft.category}
                  onChange={(value) => set('category', value)}
                  options={options.categories.map((option) => ({ value: option.value, label: label(option) }))}
                />
              </Field>

              <Field label={t.wizard.goal}>
                <Segmented
                  size="sm"
                  value={draft.goal}
                  onChange={(value) => set('goal', value)}
                  options={options.goals.map((option) => ({ value: option.value, label: label(option) }))}
                />
              </Field>

              <Field label={t.wizard.platform}>
                <Segmented
                  size="sm"
                  value={draft.platform}
                  onChange={(value) => set('platform', value)}
                  options={options.platforms.map((option) => ({ value: option.value, label: label(option) }))}
                />
              </Field>

              <Field label={t.wizard.durationLabel}>
                <Segmented
                  size="sm"
                  value={draft.duration_sec}
                  onChange={(value) => set('duration_sec', value)}
                  options={options.durations.map((seconds) => ({
                    value: seconds,
                    label: `${num(seconds)} ${t.common.seconds}`,
                  }))}
                />
              </Field>
            </>
          ) : null}

          {stepKey === 'audience' ? (
            <>
              <Field label={t.wizard.language}>
                <Segmented
                  size="sm"
                  value={draft.language}
                  onChange={(value) => set('language', value)}
                  options={options.languages.map((option) => ({ value: option.value, label: label(option) }))}
                />
              </Field>

              <Field label={t.wizard.dialect}>
                <Segmented
                  size="sm"
                  value={draft.dialect}
                  onChange={(value) => set('dialect', value)}
                  options={options.dialects.map((option) => ({ value: option.value, label: label(option) }))}
                />
              </Field>

              <Field label={t.wizard.tone}>
                <Segmented
                  size="sm"
                  value={draft.tone}
                  onChange={(value) => set('tone', value)}
                  options={options.tones.map((option) => ({ value: option.value, label: label(option) }))}
                />
              </Field>

              <Field label={t.wizard.targetAudience}>
                <input
                  className="field"
                  value={draft.target_audience}
                  placeholder={t.wizard.targetAudiencePlaceholder}
                  onChange={(event) => set('target_audience', event.target.value)}
                />
              </Field>

              <Field label={t.wizard.keyInformation} hint={t.wizard.keyInformationPlaceholder}>
                <textarea
                  className="field min-h-[120px] resize-y"
                  value={draft.key_information}
                  onChange={(event) => set('key_information', event.target.value)}
                />
              </Field>

              <Field label={t.wizard.cta}>
                <input
                  className="field"
                  value={draft.cta}
                  placeholder={t.wizard.ctaPlaceholder}
                  onChange={(event) => set('cta', event.target.value)}
                />
              </Field>
            </>
          ) : null}

          {stepKey === 'assets' ? (
            <>
              <Field label={t.wizard.productionMode} hint={locale === 'ar' ? 'Auto Smart يختار الأنسب لكل مشهد' : 'Auto Smart decides per scene'}>
                <Segmented
                  size="sm"
                  value={draft.production_mode}
                  onChange={(value) => set('production_mode', value)}
                  options={options.production_modes.map((option) => ({ value: option.value, label: label(option) }))}
                />
              </Field>

              <div className="grid gap-4 sm:grid-cols-2">
                <AssetUploader
                  kind="image"
                  label={t.wizard.uploadImages}
                  assets={assets.filter((asset) => asset.kind === 'image')}
                  onUploaded={(items) => setAssets((current) => [...current, ...items])}
                  onRemoved={(id) => setAssets((current) => current.filter((asset) => asset.id !== id))}
                />
                <AssetUploader
                  kind="video"
                  label={t.wizard.uploadVideos}
                  assets={assets.filter((asset) => asset.kind === 'video')}
                  onUploaded={(items) => setAssets((current) => [...current, ...items])}
                  onRemoved={(id) => setAssets((current) => current.filter((asset) => asset.id !== id))}
                />
                <AssetUploader
                  kind="logo"
                  label={t.wizard.uploadLogo}
                  assets={assets.filter((asset) => asset.kind === 'logo')}
                  onUploaded={(items) => setAssets((current) => [...current, ...items])}
                  onRemoved={(id) => setAssets((current) => current.filter((asset) => asset.id !== id))}
                />
                <AssetUploader
                  kind="reference"
                  isReference
                  label={t.wizard.uploadReference}
                  assets={assets.filter((asset) => asset.kind === 'reference')}
                  onUploaded={(items) => setAssets((current) => [...current, ...items])}
                  onRemoved={(id) => setAssets((current) => current.filter((asset) => asset.id !== id))}
                />
              </div>

              <Toggle
                checked={draft.voice_over_enabled}
                onChange={(value) => set('voice_over_enabled', value)}
                label={t.wizard.voiceOver}
                hint={t.wizard.voiceOverHint}
              />
            </>
          ) : null}

          {stepKey === 'review' ? (
            <div className="space-y-4">
              <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
                {[
                  [t.wizard.name, draft.name || '—'],
                  [t.wizard.category, draft.category],
                  [t.wizard.goal, draft.goal],
                  [t.wizard.platform, draft.platform.replace(/_/g, ' ')],
                  [t.wizard.durationLabel, `${num(draft.duration_sec)} ${t.common.seconds}`],
                  [t.wizard.language, draft.language.replace(/_/g, ' ')],
                  [t.wizard.dialect, draft.dialect.replace(/_/g, ' ')],
                  [t.wizard.tone, draft.tone.replace(/_/g, ' ')],
                  [t.wizard.productionMode, draft.production_mode.replace(/_/g, ' ')],
                  [t.wizard.cta, draft.cta || '—'],
                  [t.wizard.assets, `${num(assets.length)}`],
                ].map(([term, value]) => (
                  <div key={String(term)}>
                    <dt className="text-[12px] text-ink-faint">{term}</dt>
                    <dd className="text-[14px] font-medium text-ink">{value}</dd>
                  </div>
                ))}
              </dl>

              {brands && brands.items.length > 0 ? (
                <Field label={t.brands.title}>
                  <Segmented
                    size="sm"
                    value={draft.brand_kit_id ?? brands.items.find((kit) => kit.is_default)?.id ?? ''}
                    onChange={(value) => set('brand_kit_id', value || null)}
                    options={brands.items.map((kit) => ({ value: kit.id, label: kit.name_ar || kit.name }))}
                  />
                </Field>
              ) : null}

              <InlineError error={create.error} />
            </div>
          ) : null}

          <div className="flex items-center justify-between border-t border-line pt-4">
            <Button
              variant="ghost"
              icon={<Prev className="h-4 w-4" />}
              onClick={() => setStep((current) => Math.max(0, current - 1))}
              disabled={step === 0}
            >
              {t.common.back}
            </Button>

            {step < STEP_KEYS.length - 1 ? (
              <Button icon={<Next className="h-4 w-4" />} disabled={!canContinue} onClick={() => setStep((c) => c + 1)}>
                {t.common.next}
              </Button>
            ) : (
              <Button
                icon={<Sparkles className="h-4 w-4" />}
                loading={create.pending}
                disabled={!draft.name.trim()}
                onClick={() => void create.run()}
              >
                {create.pending ? t.wizard.creating : t.wizard.create}
              </Button>
            )}
          </div>
        </Card>

        <aside className="space-y-4">
          <AIDirector
            notes={[
              {
                key: 'assets',
                message_ar: 'ارفع ٤–٦ صور على الأقل — هيچي نقدر ننتج بدون توليد فيديو مكلف.',
                message_en: 'Upload at least 4-6 photos — that lets us produce without expensive AI video.',
                impact: 'high',
              },
              {
                key: 'brief',
                message_ar: 'كل سطر بالمعلومات الأساسية يصير مشهد — خلّيها قصيرة وواضحة.',
                message_en: 'Each line of key information becomes a scene — keep them short and concrete.',
                impact: 'medium',
              },
            ]}
          />
          <Card>
            <p className="section-title mb-2">{t.wizard.review}</p>
            <p className="text-[13px] leading-relaxed text-ink-muted">
              {locale === 'ar'
                ? 'بعد الإنشاء راح ننتقل مباشرة لتحليل المشروع، وبعدها ثلاث أفكار إبداعية تختار منها.'
                : 'After creation we go straight to analysis, then three creative concepts to choose from.'}
            </p>
          </Card>
        </aside>
      </div>
    </>
  );
}

export default function NewProjectPage() {
  return (
    <Suspense fallback={<LoadingBlock lines={5} />}>
      <NewProjectWizard />
    </Suspense>
  );
}
