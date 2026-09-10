'use client';

import clsx from 'clsx';
import { Check, Sparkles, Star, Wand2 } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useState } from 'react';

import { AIDirector } from '@/components/AIDirector';
import { ProjectFrame } from '@/components/ProjectFrame';
import { useDirectorMode } from '@/components/AppShell';
import {
  Badge,
  Button,
  Card,
  CardTitle,
  EmptyState,
  ErrorState,
  InlineError,
  LoadingBlock,
  Modal,
  Progress,
} from '@/components/ui';
import { useLocale } from '@/i18n/LocaleProvider';
import { api } from '@/lib/api';
import { useApi, useMutation } from '@/lib/hooks';
import type { Concept, DirectorNote, ProjectDetail } from '@/lib/types';

type ConceptsPayload = {
  items: Concept[];
  alternatives: Concept[];
  actions: { key: string; label_en: string; label_ar: string }[];
  selected_concept_id: string | null;
  director_notes: DirectorNote[];
  state: string;
};

export default function ConceptsPage() {
  return <ProjectFrame>{(project, reload) => <ConceptsView project={project} reloadProject={reload} />}</ProjectFrame>;
}

function ConceptsView({ project, reloadProject }: { project: ProjectDetail; reloadProject: () => void }) {
  const { t, locale, money, num } = useLocale();
  const router = useRouter();
  const { directorMode } = useDirectorMode();
  const { data, error, loading, reload } = useApi<ConceptsPayload>(`/projects/${project.id}/concepts`);
  const [selected, setSelected] = useState<string | null>(null);
  const [showAlternatives, setShowAlternatives] = useState(false);
  const [detail, setDetail] = useState<Concept | null>(null);

  const generate = useMutation(async (regenerate = false) => {
    await api.post(`/projects/${project.id}/concepts/generate${regenerate ? '?regenerate=true' : ''}`);
    reload();
    reloadProject();
  });

  const refine = useMutation(async (conceptId: string, action: string) => {
    await api.post(`/projects/${project.id}/concepts/${conceptId}/refine`, { action });
    reload();
  });

  const approve = useMutation(async (conceptId: string) => {
    await api.post(`/projects/${project.id}/concepts/approve`, { entity_id: conceptId });
    reloadProject();
    router.push(`/projects/${project.id}/script`);
  });

  if (loading && !data) return <LoadingBlock lines={6} />;

  const items = data?.items ?? [];
  const activeId = selected ?? data?.selected_concept_id ?? items.find((c) => c.is_recommended)?.id ?? null;

  return (
    <div className="space-y-5">
      {error ? <ErrorState error={error} onRetry={reload} /> : null}
      {generate.error ? <ErrorState error={generate.error} /> : null}

      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-[18px] font-semibold text-ink">{t.concepts.title}</h2>
          <p className="text-[13px] text-ink-muted">{t.concepts.subtitle}</p>
        </div>
        <div className="flex gap-2">
          {data && data.alternatives.length > 0 ? (
            <Button variant="secondary" size="sm" onClick={() => setShowAlternatives((v) => !v)}>
              {t.concepts.showAlternative}
            </Button>
          ) : null}
          <Button
            size="sm"
            variant={items.length ? 'secondary' : 'primary'}
            loading={generate.pending}
            icon={<Wand2 className="h-3.5 w-3.5" />}
            onClick={() => void generate.run(items.length > 0)}
          >
            {items.length ? t.common.regenerate : t.common.generate}
          </Button>
        </div>
      </div>

      <AIDirector notes={data?.director_notes} />

      {items.length === 0 ? (
        <EmptyState
          title={t.errors.noConcepts}
          hint={t.concepts.subtitle}
          action={
            <Button loading={generate.pending} onClick={() => void generate.run(false)}>
              {t.common.generate}
            </Button>
          }
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-3">
          {items.map((concept) => (
            <ConceptCard
              key={concept.id}
              concept={concept}
              active={activeId === concept.id}
              directorMode={directorMode}
              onSelect={() => setSelected(concept.id)}
              onDetails={() => setDetail(concept)}
            />
          ))}
        </div>
      )}

      {showAlternatives && data && data.alternatives.length > 0 ? (
        <Card>
          <CardTitle>{t.concepts.showAlternative}</CardTitle>
          <div className="grid gap-3 sm:grid-cols-2">
            {data.alternatives.map((concept) => (
              <button
                key={concept.id}
                type="button"
                onClick={() => setDetail(concept)}
                className="rounded-xl border border-line bg-raised p-3 text-start hover:border-line-strong"
              >
                <p className="text-[14px] font-medium text-ink">{concept.name}</p>
                <p className="mt-1 line-clamp-2 text-[12.5px] text-ink-muted">{concept.one_line_idea}</p>
                <p className="ltr-nums mt-2 text-[12px] text-ink-faint">{num(concept.score_total)}/100</p>
              </button>
            ))}
          </div>
        </Card>
      ) : null}

      {items.length > 0 ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-line bg-surface p-4">
          <div className="flex flex-wrap gap-2">
            {(data?.actions ?? []).map((action) => (
              <Button
                key={action.key}
                size="sm"
                variant="secondary"
                disabled={!activeId || refine.pending}
                onClick={() => activeId && void refine.run(activeId, action.key)}
              >
                {locale === 'ar' ? action.label_ar : action.label_en}
              </Button>
            ))}
          </div>
          <div className="flex items-center gap-3">
            <InlineError error={approve.error} />
            <Button
              size="lg"
              disabled={!activeId}
              loading={approve.pending}
              icon={<Check className="h-4 w-4" />}
              onClick={() => activeId && void approve.run(activeId)}
            >
              {t.concepts.approve}
            </Button>
          </div>
        </div>
      ) : null}

      <Modal open={Boolean(detail)} onClose={() => setDetail(null)} title={detail?.name ?? ''} wide>
        {detail ? (
          <div className="space-y-4 text-[13.5px]">
            <Section title={t.concepts.hook}>{detail.hook}</Section>
            <Section title={t.concepts.idea}>{detail.one_line_idea}</Section>
            <Section title={t.concepts.direction}>{detail.creative_direction}</Section>
            <Section title={t.storyboard.title}>{detail.visual_style}</Section>
            <Section title={t.wizard.cta}>{detail.cta_style}</Section>
            <Section title={t.concepts.why}>{detail.why_this_works}</Section>
            <div>
              <p className="section-title mb-2">{t.concepts.scores}</p>
              <div className="grid gap-2 sm:grid-cols-2">
                {Object.entries(detail.scores).map(([key, value]) => (
                  <div key={key}>
                    <div className="mb-1 flex items-center justify-between text-[12px]">
                      <span className="text-ink-muted">{key.replace(/_/g, ' ')}</span>
                      <span className="ltr-nums text-ink-soft">{Math.round(value)}</span>
                    </div>
                    <Progress value={value} />
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : null}
      </Modal>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="section-title mb-1">{title}</p>
      <p className="leading-relaxed text-ink-soft">{children}</p>
    </div>
  );
}

function ConceptCard({
  concept,
  active,
  directorMode,
  onSelect,
  onDetails,
}: {
  concept: Concept;
  active: boolean;
  directorMode: boolean;
  onSelect: () => void;
  onDetails: () => void;
}) {
  const { t, money, num } = useLocale();
  return (
    <article
      onClick={onSelect}
      className={clsx(
        'card card-hover cursor-pointer p-5 transition',
        active && 'border-accent shadow-focus',
      )}
    >
      <div className="mb-3 flex items-start justify-between gap-2">
        <Badge tone={concept.is_recommended ? 'accent' : 'neutral'} icon={concept.is_recommended ? <Star className="h-3 w-3" /> : undefined}>
          {concept.is_recommended ? t.common.recommended : concept.angle.replace(/_/g, ' ')}
        </Badge>
        <span className="ltr-nums text-[13px] font-semibold text-ink">{num(concept.score_total)}</span>
      </div>

      <h3 className="text-[16px] font-semibold leading-snug text-ink">{concept.name}</h3>
      <p className="mt-1 text-[12px] text-ink-faint">{concept.name_en}</p>

      <div className="mt-3 rounded-xl bg-canvas px-3 py-2.5">
        <p className="text-[11.5px] font-medium text-ink-faint">{t.concepts.hook}</p>
        <p className="mt-0.5 text-[14px] font-medium leading-relaxed text-ink">{concept.hook}</p>
      </div>

      <p className="mt-3 line-clamp-3 text-[13px] leading-relaxed text-ink-muted">{concept.one_line_idea}</p>

      <div className="mt-4 flex items-center justify-between border-t border-line pt-3 text-[12px]">
        <span className="ltr-nums text-ink-soft">{money(concept.estimated_cost_usd)}</span>
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onDetails();
          }}
          className="font-medium text-accent hover:underline"
        >
          {t.common.edit}
        </button>
      </div>

      {directorMode ? (
        <div className="mt-3 space-y-1 rounded-xl bg-graphite-900 p-3 text-[11px] text-slate-300">
          <p>mode: {concept.recommended_mode}</p>
          <p>voice: {concept.recommended_voice}</p>
          <p>version: {concept.version}</p>
        </div>
      ) : null}

      {active ? (
        <p className="mt-3 flex items-center gap-1.5 text-[12px] font-semibold text-accent">
          <Sparkles className="h-3.5 w-3.5" />
          {t.common.selected}
        </p>
      ) : null}
    </article>
  );
}
