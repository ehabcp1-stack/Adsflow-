'use client';

import clsx from 'clsx';
import { FileVideo, ImageIcon, Trash2, Upload } from 'lucide-react';
import { useRef, useState } from 'react';

import { useLocale } from '@/i18n/LocaleProvider';
import { ApiError, api, mediaUrl } from '@/lib/api';
import type { Asset } from '@/lib/types';

import { Badge, Button, InlineError } from './ui';

/**
 * Upload images, video, logo and reference media. Analysis runs server-side on
 * upload, so quality/hero metadata is available immediately.
 */
export function AssetUploader({
  projectId,
  kind = 'image',
  assets,
  onUploaded,
  onRemoved,
  label,
  accept,
  isReference = false,
}: {
  projectId?: string;
  kind?: 'image' | 'video' | 'logo' | 'reference';
  assets: Asset[];
  onUploaded: (assets: Asset[]) => void;
  onRemoved?: (id: string) => void;
  label: string;
  accept?: string;
  isReference?: boolean;
}) {
  const { t } = useLocale();
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function upload(files: FileList | null) {
    if (!files || files.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      Array.from(files).forEach((file) => form.append('files', file));
      form.append('kind', kind);
      form.append('is_project_reference', String(isReference));
      if (projectId) form.append('project_id', projectId);
      const result = await api.upload<{ items: Asset[] }>('/assets/upload', form);
      onUploaded(result.items);
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = '';
    }
  }

  return (
    <div>
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          void upload(event.dataTransfer.files);
        }}
        onClick={() => inputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(event) => event.key === 'Enter' && inputRef.current?.click()}
        className={clsx(
          'flex cursor-pointer flex-col items-center justify-center rounded-2xl border border-dashed px-4 py-7 text-center transition',
          dragging ? 'border-accent bg-accent-soft' : 'border-line bg-raised hover:border-line-strong',
        )}
      >
        <span className="mb-2 rounded-xl bg-canvas p-2.5 text-ink-faint">
          {kind === 'video' ? <FileVideo className="h-5 w-5" /> : <ImageIcon className="h-5 w-5" />}
        </span>
        <p className="text-[14px] font-medium text-ink">{label}</p>
        <p className="mt-0.5 text-[12px] text-ink-muted">{t.wizard.dropHere}</p>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          className="mt-3"
          loading={busy}
          icon={<Upload className="h-3.5 w-3.5" />}
          onClick={(event) => {
            event.stopPropagation();
            inputRef.current?.click();
          }}
        >
          {t.media.upload}
        </Button>
        <input
          ref={inputRef}
          type="file"
          multiple
          hidden
          accept={accept ?? (kind === 'video' ? 'video/*' : 'image/*')}
          onChange={(event) => void upload(event.target.files)}
        />
      </div>

      <InlineError error={error} />

      {assets.length > 0 ? (
        <ul className="mt-3 grid grid-cols-3 gap-2 sm:grid-cols-4">
          {assets.map((asset) => (
            <li key={asset.id} className="group relative overflow-hidden rounded-xl border border-line bg-canvas">
              <div className="aspect-square">
                {asset.kind === 'video' ? (
                  <img src={mediaUrl(asset.thumbnail_url)} alt={asset.filename} className="h-full w-full object-cover" />
                ) : (
                  <img src={mediaUrl(asset.url)} alt={asset.filename} className="h-full w-full object-cover" />
                )}
              </div>
              {asset.quality_score ? (
                <span className="ltr-nums absolute start-1.5 top-1.5 rounded-full bg-black/55 px-1.5 py-0.5 text-[10px] font-semibold text-white">
                  {Math.round(asset.quality_score)}
                </span>
              ) : null}
              {onRemoved ? (
                <button
                  type="button"
                  onClick={() => onRemoved(asset.id)}
                  className="absolute end-1.5 top-1.5 rounded-lg bg-black/55 p-1 text-white opacity-0 transition group-hover:opacity-100"
                  aria-label={t.common.delete}
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              ) : null}
              {asset.is_project_reference ? (
                <span className="absolute inset-x-1.5 bottom-1.5">
                  <Badge tone="gold" className="w-full justify-center !text-[9.5px]">
                    {t.media.reference}
                  </Badge>
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
