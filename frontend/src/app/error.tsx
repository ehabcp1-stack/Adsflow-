'use client';

import { useEffect } from 'react';

import { Button, EmptyState } from '@/components/ui';
import { useLocale } from '@/i18n/LocaleProvider';

export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const { t } = useLocale();

  useEffect(() => {
    // Never show a raw stack trace to a normal user; log it for developers.
    console.error('[AdFlow]', error);
  }, [error]);

  return (
    <div className="py-16">
      <EmptyState title={t.errors.generic} hint={t.errors.backendDownHint} action={<Button onClick={reset}>{t.common.retry}</Button>} />
    </div>
  );
}
