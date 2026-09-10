'use client';

/**
 * Dynamic direction switching. RTL is not bolted on: the whole document
 * direction, font stack and numeral formatting follow the active locale.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import { Dictionary, Locale, dictionary } from './dictionary';

type LocaleContextValue = {
  locale: Locale;
  dir: 'rtl' | 'ltr';
  isRTL: boolean;
  t: Dictionary;
  setLocale: (next: Locale) => void;
  toggleLocale: () => void;
  /** Locale-aware number formatting (Arabic keeps Western digits for clarity in ads). */
  num: (value: number, options?: Intl.NumberFormatOptions) => string;
  money: (value: number) => string;
  timecode: (seconds: number) => string;
  date: (iso?: string | null) => string;
};

const LocaleContext = createContext<LocaleContextValue | null>(null);
const STORAGE_KEY = 'adflow.locale';

export function LocaleProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>('ar');

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY) as Locale | null;
      if (stored === 'ar' || stored === 'en') setLocaleState(stored);
    } catch {
      /* storage can be unavailable — default locale still works */
    }
  }, []);

  useEffect(() => {
    const dir = locale === 'ar' ? 'rtl' : 'ltr';
    document.documentElement.lang = locale;
    document.documentElement.dir = dir;
    document.documentElement.dataset.locale = locale;
    try {
      window.localStorage.setItem(STORAGE_KEY, locale);
    } catch {
      /* ignore */
    }
  }, [locale]);

  const setLocale = useCallback((next: Locale) => setLocaleState(next), []);
  const toggleLocale = useCallback(() => setLocaleState((c) => (c === 'ar' ? 'en' : 'ar')), []);

  const value = useMemo<LocaleContextValue>(() => {
    const intlLocale = locale === 'ar' ? 'ar-IQ-u-nu-latn' : 'en-US';
    return {
      locale,
      dir: locale === 'ar' ? 'rtl' : 'ltr',
      isRTL: locale === 'ar',
      t: dictionary[locale] as unknown as Dictionary,
      setLocale,
      toggleLocale,
      num: (v, options) => new Intl.NumberFormat(intlLocale, options).format(Number.isFinite(v) ? v : 0),
      money: (v) =>
        `$${new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(
          Number.isFinite(v) ? v : 0,
        )}`,
      // Timecodes always stay LTR — mm:ss is universal in editing tools.
      timecode: (seconds) => {
        const total = Math.max(0, Math.round(seconds * 100) / 100);
        const m = Math.floor(total / 60);
        const s = Math.floor(total % 60);
        const cs = Math.round((total - Math.floor(total)) * 10);
        return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${cs}`;
      },
      date: (iso) => {
        if (!iso) return '—';
        try {
          return new Intl.DateTimeFormat(locale === 'ar' ? 'ar-IQ-u-nu-latn' : 'en-GB', {
            day: '2-digit',
            month: 'short',
            year: 'numeric',
          }).format(new Date(iso));
        } catch {
          return '—';
        }
      },
    };
  }, [locale, setLocale, toggleLocale]);

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useLocale(): LocaleContextValue {
  const context = useContext(LocaleContext);
  if (!context) throw new Error('useLocale must be used inside <LocaleProvider>');
  return context;
}

/** Pick the right label from a bilingual API payload. */
export function useBilingual() {
  const { locale } = useLocale();
  return (item: { label_ar?: string | null; label_en?: string | null } | null | undefined, fallback = '') =>
    (locale === 'ar' ? item?.label_ar || item?.label_en : item?.label_en || item?.label_ar) || fallback;
}
