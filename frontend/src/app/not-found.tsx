'use client';

import Link from 'next/link';

import { Button, EmptyState } from '@/components/ui';
import { useLocale } from '@/i18n/LocaleProvider';

export default function NotFound() {
  const { t } = useLocale();
  return (
    <div className="py-16">
      <EmptyState
        title={t.errors.notFound}
        hint="AdFlow AI · by TADAFQ"
        action={
          <Link href="/dashboard">
            <Button>{t.nav.dashboard}</Button>
          </Link>
        }
      />
    </div>
  );
}
