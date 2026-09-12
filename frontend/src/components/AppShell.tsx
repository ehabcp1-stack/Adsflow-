'use client';

import clsx from 'clsx';
import { FolderKanban, Images, LayoutDashboard, Menu, Palette, Settings, Sparkles, X } from 'lucide-react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { createContext, useContext, useState } from 'react';

import { useLocale } from '@/i18n/LocaleProvider';
import { DEMO_MODE } from '@/lib/api';
import { useApi, useLocalToggle } from '@/lib/hooks';
import type { SystemHealth } from '@/lib/types';

import { Badge, Toggle } from './ui';

/** Honest banner: the hosted build is a showcase, not a working install. */
function DemoBanner() {
  const { t } = useLocale();
  if (!DEMO_MODE) return null;
  return (
    <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 bg-ink px-4 py-2 text-center text-[12.5px] text-white/85">
      <span className="rounded-full bg-white/15 px-2 py-0.5 text-[11px] font-semibold text-white">
        {t.demoBanner.badge}
      </span>
      <span>{t.demoBanner.text}</span>
      <span className="text-white/55">{t.demoBanner.cta}</span>
    </div>
  );
}

/* --------------------------------------------------- Director Mode context */
const DirectorModeContext = createContext<{ directorMode: boolean; setDirectorMode: (v: boolean) => void }>({
  directorMode: false,
  setDirectorMode: () => {},
});

export const useDirectorMode = () => useContext(DirectorModeContext);

/* ------------------------------------------------------------------ Wordmark */
export function Wordmark({ compact = false }: { compact?: boolean }) {
  const { t } = useLocale();
  return (
    <Link href="/dashboard" className="flex items-center gap-2.5">
      <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-ink text-white">
        <Sparkles className="h-4 w-4" />
      </span>
      {!compact ? (
        <span className="leading-tight">
          <span className="block text-[15px] font-semibold tracking-tight text-ink">AdFlow AI</span>
          <span className="block text-[11px] text-ink-faint">
            {t.brand.by} {t.brand.parent}
          </span>
        </span>
      ) : null}
    </Link>
  );
}

/* ------------------------------------------------------------------ Language */
export function LanguageToggle() {
  const { locale, setLocale } = useLocale();
  return (
    <div className="flex rounded-lg border border-line bg-canvas p-0.5">
      {(['ar', 'en'] as const).map((code) => (
        <button
          key={code}
          type="button"
          onClick={() => setLocale(code)}
          className={clsx(
            'rounded-md px-2.5 py-1 text-[12px] font-semibold uppercase transition',
            locale === code ? 'bg-surface text-ink shadow-card' : 'text-ink-faint hover:text-ink-soft',
          )}
        >
          {code}
        </button>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------- Runtime */
/**
 * States the real provider runtime instead of claiming one. Reads
 * `/system/health`; renders nothing until it answers, so the shell never
 * asserts "mock" (or "real") on a guess. Clicking it opens Settings, where
 * the full provider list lives — so this is a control, not a label.
 */
function RuntimeBadge() {
  const { t } = useLocale();
  const { data } = useApi<SystemHealth>('/system/health');
  if (!data) return null;
  const mock = data.runtime_mode === 'mock';
  return (
    <Link href="/settings" className="block">
      <Badge tone={mock ? 'accent' : 'ok'} className="w-full justify-center">
        {mock ? t.settings.mockMode : t.settings.realProvider} · {t.settings.providers}
      </Badge>
    </Link>
  );
}

/* -------------------------------------------------------------------- Shell */
const NAV = [
  { href: '/dashboard', key: 'dashboard', icon: LayoutDashboard },
  { href: '/projects', key: 'projects', icon: FolderKanban },
  { href: '/brands', key: 'brands', icon: Palette },
  { href: '/media', key: 'media', icon: Images },
  { href: '/settings', key: 'settings', icon: Settings },
] as const;

export function AppShell({ children }: { children: React.ReactNode }) {
  const { t } = useLocale();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [directorMode, setDirectorMode] = useLocalToggle('adflow.directorMode', false);

  const nav = (
    <nav className="flex flex-col gap-1">
      {NAV.map(({ href, key, icon: Icon }) => {
        const active = pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link
            key={href}
            href={href}
            onClick={() => setOpen(false)}
            className={clsx(
              'flex items-center gap-3 rounded-xl px-3 py-2.5 text-[14px] font-medium transition',
              active ? 'bg-accent-soft text-accent-dark' : 'text-ink-soft hover:bg-canvas',
            )}
          >
            <Icon className={clsx('h-[18px] w-[18px]', active ? 'text-accent' : 'text-ink-faint')} />
            {t.nav[key]}
          </Link>
        );
      })}
    </nav>
  );

  return (
    <DirectorModeContext.Provider value={{ directorMode, setDirectorMode }}>
      <div className="min-h-screen bg-canvas">
        <DemoBanner />
        {/* Mobile top bar */}
        <div className="sticky top-0 z-30 flex items-center justify-between border-b border-line bg-surface/90 px-4 py-3 backdrop-blur lg:hidden">
          <Wordmark />
          <div className="flex items-center gap-2">
            <LanguageToggle />
            <button type="button" onClick={() => setOpen((v) => !v)} className="rounded-lg p-2 text-ink-soft hover:bg-canvas">
              {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>
          </div>
        </div>

        {open ? (
          <div className="border-b border-line bg-surface px-4 py-3 lg:hidden">
            {nav}
            <div className="mt-4 border-t border-line pt-4">
              <Toggle checked={directorMode} onChange={setDirectorMode} label={t.common.directorMode} />
            </div>
          </div>
        ) : null}

        <div className="mx-auto flex w-full max-w-[1560px]">
          {/* Desktop sidebar */}
          <aside className="sticky top-0 hidden h-screen w-[248px] shrink-0 flex-col border-e border-line bg-surface px-4 py-5 lg:flex">
            <Wordmark />
            <div className="mt-7 flex-1">{nav}</div>
            <div className="space-y-3 rounded-2xl border border-line bg-raised p-3">
              <Toggle checked={directorMode} onChange={setDirectorMode} label={t.common.directorMode} />
              <div className="flex items-center justify-between">
                <span className="text-[12px] text-ink-faint">{t.common.language}</span>
                <LanguageToggle />
              </div>
              <RuntimeBadge />
            </div>
          </aside>

          <main className="min-w-0 flex-1 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">{children}</main>
        </div>
      </div>
    </DirectorModeContext.Provider>
  );
}

/* ------------------------------------------------------------- Page heading */
export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-[26px] font-semibold tracking-tight text-ink sm:text-[30px]">{title}</h1>
        {subtitle ? <p className="mt-1 text-[14px] text-ink-muted">{subtitle}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}
