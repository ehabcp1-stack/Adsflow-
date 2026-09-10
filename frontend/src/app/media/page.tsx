'use client';

import { Images, Trash2 } from 'lucide-react';
import { useState } from 'react';

import { PageHeader } from '@/components/AppShell';
import { AssetUploader } from '@/components/AssetUploader';
import { Badge, Button, Card, EmptyState, ErrorState, LoadingBlock, Modal, Tabs } from '@/components/ui';
import { useLocale } from '@/i18n/LocaleProvider';
import { api, mediaUrl } from '@/lib/api';
import { useApi, useMutation } from '@/lib/hooks';
import type { Asset } from '@/lib/types';

type Filter = 'all' | 'image' | 'video';

export default function MediaPage() {
  const { t, num, date } = useLocale();
  const [filter, setFilter] = useState<Filter>('all');
  const [detail, setDetail] = useState<Asset | null>(null);
  const { data, error, loading, reload } = useApi<{ items: Asset[] }>('/assets');

  const remove = useMutation(async (id: string) => {
    await api.delete(`/assets/${id}`);
    setDetail(null);
    reload();
  });

  const items = (data?.items ?? []).filter((asset) => (filter === 'all' ? true : asset.kind === filter));

  return (
    <>
      <PageHeader title={t.media.title} subtitle={t.media.subtitle} />

      <div className="mb-5 grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="max-w-md">
          <Tabs<Filter>
            value={filter}
            onChange={setFilter}
            tabs={[
              { value: 'all', label: t.common.all, count: data?.items.length },
              { value: 'image', label: t.wizard.uploadImages, count: data?.items.filter((a) => a.kind === 'image').length },
              { value: 'video', label: t.wizard.uploadVideos, count: data?.items.filter((a) => a.kind === 'video').length },
            ]}
          />
        </div>
        <AssetUploader kind="image" label={t.media.upload} assets={[]} onUploaded={() => reload()} />
      </div>

      {error ? <ErrorState error={error} onRetry={reload} /> : null}
      {loading && !data ? <LoadingBlock lines={4} /> : null}

      {items.length === 0 && !loading ? (
        <EmptyState title={t.media.empty} icon={<Images className="h-5 w-5" />} />
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5 xl:grid-cols-6">
          {items.map((asset) => (
            <button
              key={asset.id}
              type="button"
              onClick={() => setDetail(asset)}
              className="card card-hover overflow-hidden p-0 text-start"
            >
              <div className="relative aspect-square bg-graphite-900">
                <img src={mediaUrl(asset.thumbnail_url || asset.url)} alt={asset.filename} className="h-full w-full object-cover" />
                {asset.quality_score ? (
                  <span className="ltr-nums absolute start-1.5 top-1.5 rounded-full bg-black/60 px-1.5 py-0.5 text-[10px] font-bold text-white">
                    {Math.round(asset.quality_score)}
                  </span>
                ) : null}
                {asset.kind === 'video' ? (
                  <span className="absolute end-1.5 top-1.5 rounded bg-black/60 px-1.5 py-0.5 text-[10px] text-white">video</span>
                ) : null}
              </div>
              <div className="p-2">
                <p className="ltr-nums truncate text-[11.5px] text-ink-soft">{asset.filename}</p>
                <p className="text-[10.5px] text-ink-faint">{asset.category ?? asset.kind}</p>
              </div>
            </button>
          ))}
        </div>
      )}

      <Modal open={Boolean(detail)} onClose={() => setDetail(null)} title={detail?.filename ?? ''} wide>
        {detail ? (
          <div className="grid gap-5 sm:grid-cols-[220px_minmax(0,1fr)]">
            <img src={mediaUrl(detail.url)} alt="" className="w-full rounded-xl border border-line object-cover" />
            <div className="space-y-3 text-[13px]">
              <div className="flex flex-wrap gap-2">
                <Badge tone={detail.usable ? 'ok' : 'warn'}>{detail.usable ? t.media.usable : t.media.notUsable}</Badge>
                {detail.is_project_reference ? <Badge tone="gold">reference</Badge> : null}
                <Badge tone="neutral">{detail.orientation}</Badge>
              </div>
              <Row label={t.media.quality} value={detail.quality_score ? num(Math.round(detail.quality_score)) : '—'} />
              <Row label={t.media.hero} value={detail.hero_potential ? num(Math.round(detail.hero_potential)) : '—'} />
              <Row label={t.wizard.category} value={detail.category ?? '—'} />
              <Row label={t.analysis.assets} value={detail.suggested_use ?? '—'} />
              <Row label={t.common.updated} value={date(detail.created_at)} />
              {detail.analysis?.strong_segments ? (
                <div>
                  <p className="section-title mb-1">segments</p>
                  <ul className="ltr-nums space-y-1 text-[12px] text-ink-muted">
                    {detail.analysis.strong_segments.map((segment: any, index: number) => (
                      <li key={index}>
                        {segment.start}s → {segment.end}s · {Math.round(segment.score)}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              <Button variant="secondary" size="sm" icon={<Trash2 className="h-3.5 w-3.5" />} loading={remove.pending} onClick={() => void remove.run(detail.id)}>
                {t.common.delete}
              </Button>
            </div>
          </div>
        ) : null}
      </Modal>
    </>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between border-b border-line/60 pb-1.5">
      <span className="text-ink-faint">{label}</span>
      <span className="font-medium text-ink-soft">{value}</span>
    </div>
  );
}
