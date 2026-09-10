'use client';

/** AdFlow AI design-system primitives — restrained, premium, reusable. */
import clsx from 'clsx';
import { AlertTriangle, Check, Inbox, Loader2, RefreshCw, X } from 'lucide-react';
import { useEffect } from 'react';

import { useLocale } from '@/i18n/LocaleProvider';

/* -------------------------------------------------------------------- Button */
type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'dark';
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
  icon?: React.ReactNode;
  full?: boolean;
};

export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  icon,
  full,
  className,
  children,
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={clsx(
        'inline-flex items-center justify-center gap-2 rounded-xl font-medium transition duration-150',
        'disabled:cursor-not-allowed disabled:opacity-50',
        size === 'sm' && 'px-3 py-1.5 text-[13px]',
        size === 'md' && 'px-4 py-2.5 text-[14px]',
        size === 'lg' && 'px-5 py-3 text-[15px]',
        variant === 'primary' && 'bg-accent text-white shadow-card hover:bg-accent-dark active:scale-[.99]',
        variant === 'secondary' && 'border border-line bg-surface text-ink-soft hover:border-line-strong hover:bg-canvas',
        variant === 'ghost' && 'text-ink-soft hover:bg-canvas',
        variant === 'danger' && 'bg-danger text-white hover:brightness-95',
        variant === 'dark' && 'bg-graphite-700 text-slate-100 hover:bg-graphite-600',
        full && 'w-full',
        className,
      )}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : icon}
      {children}
    </button>
  );
}

/* ---------------------------------------------------------------------- Card */
export function Card({
  className,
  children,
  padded = true,
  ...rest
}: React.HTMLAttributes<HTMLDivElement> & { padded?: boolean }) {
  return (
    <div {...rest} className={clsx('card', padded && 'p-5', className)}>
      {children}
    </div>
  );
}

export function CardTitle({ children, action }: { children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="mb-4 flex items-start justify-between gap-3">
      <h3 className="text-[15px] font-semibold text-ink">{children}</h3>
      {action}
    </div>
  );
}

/* --------------------------------------------------------------------- Badge */
export function Badge({
  tone = 'neutral',
  children,
  icon,
  className,
}: {
  tone?: 'neutral' | 'accent' | 'ok' | 'warn' | 'danger' | 'gold' | 'dark';
  children: React.ReactNode;
  icon?: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11.5px] font-semibold',
        tone === 'neutral' && 'bg-canvas text-ink-muted',
        tone === 'accent' && 'bg-accent-soft text-accent-dark',
        tone === 'ok' && 'bg-ok/10 text-ok',
        tone === 'warn' && 'bg-warn/10 text-warn',
        tone === 'danger' && 'bg-danger/10 text-danger',
        tone === 'gold' && 'bg-gold/12 text-gold',
        tone === 'dark' && 'bg-graphite-700 text-slate-200',
        className,
      )}
    >
      {icon}
      {children}
    </span>
  );
}

/* ------------------------------------------------------------------ Progress */
export function Progress({ value, tone = 'accent', className }: { value: number; tone?: 'accent' | 'ok' | 'warn' | 'danger'; className?: string }) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div className={clsx('h-1.5 w-full overflow-hidden rounded-full bg-line', className)}>
      <div
        className={clsx(
          'h-full rounded-full transition-all duration-500',
          tone === 'accent' && 'bg-accent',
          tone === 'ok' && 'bg-ok',
          tone === 'warn' && 'bg-warn',
          tone === 'danger' && 'bg-danger',
        )}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

/* ---------------------------------------------------------------- ScoreRing */
export function ScoreRing({ value, size = 92, label }: { value: number; size?: number; label?: string }) {
  const radius = (size - 10) / 2;
  const circumference = 2 * Math.PI * radius;
  const pct = Math.max(0, Math.min(100, value));
  const color = pct >= 90 ? '#0E9F6E' : pct >= 85 ? '#D97706' : '#DC2626';
  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={radius} stroke="#E7EAEE" strokeWidth="7" fill="none" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke={color}
          strokeWidth="7"
          fill="none"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference - (pct / 100) * circumference}
          className="transition-all duration-700"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="ltr-nums text-[19px] font-bold text-ink">{Math.round(pct)}</span>
        {label ? <span className="text-[10px] text-ink-faint">{label}</span> : null}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------- Toggle */
export function Toggle({
  checked,
  onChange,
  label,
  hint,
  disabled,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label?: string;
  hint?: string;
  disabled?: boolean;
}) {
  return (
    <label className={clsx('flex items-center justify-between gap-3', disabled && 'opacity-50')}>
      {label ? (
        <span>
          <span className="block text-[14px] font-medium text-ink">{label}</span>
          {hint ? <span className="block text-[12px] text-ink-muted">{hint}</span> : null}
        </span>
      ) : null}
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={clsx(
          'relative h-6 w-11 shrink-0 rounded-full transition',
          checked ? 'bg-accent' : 'bg-line-strong',
        )}
      >
        <span
          className={clsx(
            'absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all',
            checked ? 'start-[22px]' : 'start-0.5',
          )}
        />
      </button>
    </label>
  );
}

/* -------------------------------------------------------------------- Slider */
export function Slider({
  value,
  onChange,
  min = 0,
  max = 1,
  step = 0.05,
  label,
  format,
}: {
  value: number;
  onChange: (next: number) => void;
  min?: number;
  max?: number;
  step?: number;
  label?: string;
  format?: (value: number) => string;
}) {
  return (
    <div>
      {label ? (
        <div className="mb-1.5 flex items-center justify-between">
          <span className="text-[13px] font-medium text-ink-soft">{label}</span>
          <span className="ltr-nums text-[12px] text-ink-muted">{format ? format(value) : value.toFixed(2)}</span>
        </div>
      ) : null}
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-line accent-accent"
      />
    </div>
  );
}

/* --------------------------------------------------------------------- Field */
export function Field({
  label,
  hint,
  required,
  children,
}: {
  label: string;
  hint?: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="label">
        {label}
        {required ? <span className="text-danger"> *</span> : null}
      </label>
      {children}
      {hint ? <p className="mt-1 text-[12px] text-ink-muted">{hint}</p> : null}
    </div>
  );
}

/* ------------------------------------------------------------------ Segmented */
export function Segmented<T extends string | number>({
  options,
  value,
  onChange,
  size = 'md',
}: {
  options: { value: T; label: string; hint?: string }[];
  value: T;
  onChange: (next: T) => void;
  size?: 'sm' | 'md';
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((option) => (
        <button
          key={String(option.value)}
          type="button"
          onClick={() => onChange(option.value)}
          className={clsx(
            'rounded-xl border text-start transition',
            size === 'sm' ? 'px-3 py-1.5 text-[13px]' : 'px-3.5 py-2 text-[14px]',
            value === option.value
              ? 'border-accent bg-accent-soft font-semibold text-accent-dark shadow-focus'
              : 'border-line bg-surface text-ink-soft hover:border-line-strong',
          )}
        >
          <span className="block">{option.label}</span>
          {option.hint ? <span className="block text-[11px] font-normal text-ink-faint">{option.hint}</span> : null}
        </button>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------------- Tabs */
export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { value: T; label: string; count?: number }[];
  value: T;
  onChange: (next: T) => void;
}) {
  return (
    <div className="flex gap-1 rounded-xl border border-line bg-canvas p-1">
      {tabs.map((tab) => (
        <button
          key={tab.value}
          type="button"
          onClick={() => onChange(tab.value)}
          className={clsx(
            'flex-1 rounded-lg px-3 py-1.5 text-[13px] font-medium transition',
            value === tab.value ? 'bg-surface text-ink shadow-card' : 'text-ink-muted hover:text-ink-soft',
          )}
        >
          {tab.label}
          {tab.count !== undefined ? <span className="ltr-nums ms-1.5 text-ink-faint">({tab.count})</span> : null}
        </button>
      ))}
    </div>
  );
}

/* --------------------------------------------------------------------- Modal */
export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  wide,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const handler = (event: KeyboardEvent) => event.key === 'Escape' && onClose();
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-ink/25 p-0 backdrop-blur-[2px] sm:items-center sm:p-6">
      <div
        className={clsx(
          'animate-fade-up max-h-[92vh] w-full overflow-y-auto rounded-t-3xl bg-surface shadow-lift sm:rounded-2xl',
          wide ? 'sm:max-w-3xl' : 'sm:max-w-lg',
        )}
      >
        <div className="sticky top-0 flex items-center justify-between border-b border-line bg-surface px-5 py-4">
          <h3 className="text-[16px] font-semibold text-ink">{title}</h3>
          <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-ink-muted hover:bg-canvas">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="px-5 py-5">{children}</div>
        {footer ? <div className="sticky bottom-0 border-t border-line bg-surface px-5 py-4">{footer}</div> : null}
      </div>
    </div>
  );
}

/* --------------------------------------------------------------------- States */
export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx('skeleton', className)} />;
}

export function LoadingBlock({ lines = 3 }: { lines?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: lines }).map((_, index) => (
        <Skeleton key={index} className={clsx('h-4', index === 0 ? 'w-1/3' : index % 2 ? 'w-full' : 'w-4/5')} />
      ))}
    </div>
  );
}

export function EmptyState({
  title,
  hint,
  action,
  icon,
}: {
  title: string;
  hint?: string;
  action?: React.ReactNode;
  icon?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-line bg-raised px-6 py-12 text-center">
      <div className="mb-3 rounded-2xl bg-canvas p-3 text-ink-faint">{icon ?? <Inbox className="h-5 w-5" />}</div>
      <p className="text-[15px] font-medium text-ink">{title}</p>
      {hint ? <p className="mt-1 max-w-sm text-[13px] text-ink-muted">{hint}</p> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: { code?: string; message: string; messageAr?: string } | null; onRetry?: () => void }) {
  const { t, locale } = useLocale();
  if (!error) return null;
  const offline = error.code === 'network_error';
  const message = locale === 'ar' ? error.messageAr || error.message : error.message;
  return (
    <div className="rounded-2xl border border-warn/25 bg-warn/[0.06] p-5">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-warn" />
        <div className="flex-1">
          <p className="text-[14px] font-semibold text-ink">{offline ? t.errors.backendDown : message}</p>
          <p className="mt-1 text-[13px] text-ink-muted">
            {offline ? t.errors.backendDownHint : t.errors.generic}
          </p>
          {onRetry ? (
            <Button variant="secondary" size="sm" className="mt-3" icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={onRetry}>
              {t.common.retry}
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function InlineError({ error }: { error: { code?: string; message: string; messageAr?: string } | null }) {
  const { locale } = useLocale();
  if (!error) return null;
  return (
    <p className="mt-2 flex items-start gap-1.5 text-[13px] text-danger">
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      {locale === 'ar' ? error.messageAr || error.message : error.message}
    </p>
  );
}

/* ---------------------------------------------------------------------- Stat */
export function Stat({
  label,
  value,
  sub,
  tone = 'neutral',
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  tone?: 'neutral' | 'accent' | 'ok' | 'warn';
}) {
  return (
    <div className="card p-4">
      <p className="text-[12.5px] font-medium text-ink-muted">{label}</p>
      <p
        className={clsx(
          'ltr-nums mt-1 text-[24px] font-semibold leading-tight',
          tone === 'accent' && 'text-accent-dark',
          tone === 'ok' && 'text-ok',
          tone === 'warn' && 'text-warn',
          tone === 'neutral' && 'text-ink',
        )}
      >
        {value}
      </p>
      {sub ? <p className="mt-0.5 text-[12px] text-ink-faint">{sub}</p> : null}
    </div>
  );
}

/* -------------------------------------------------------------- CheckListItem */
export function CheckItem({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-2 text-[13px]">
      <span
        className={clsx(
          'mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full',
          ok ? 'bg-ok/12 text-ok' : 'bg-warn/12 text-warn',
        )}
      >
        {ok ? <Check className="h-3 w-3" /> : <AlertTriangle className="h-2.5 w-2.5" />}
      </span>
      <span className={ok ? 'text-ink-soft' : 'text-ink'}>{children}</span>
    </li>
  );
}
