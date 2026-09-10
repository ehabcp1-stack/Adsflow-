/**
 * Single source of truth for runtime configuration.
 *
 * Nothing else in the app may read `process.env` or reference a host/port.
 * Three runtime modes, chosen by configuration — never by scattered checks:
 *
 *   mock         no public backend needed. Every API call is answered from the
 *                bundled demo snapshot. This is what the Netlify deployment
 *                runs until the FastAPI backend is publicly hosted.
 *   development  talks to a developer backend (default http://localhost:8000)
 *                while engineering locally.
 *   production   talks to a publicly deployed FastAPI API.
 *
 * Resolution rules:
 *   1. NEXT_PUBLIC_DEMO_MODE=true          → mock (explicit wins)
 *   2. NEXT_PUBLIC_API_BASE_URL is set     → production (or development)
 *   3. neither, and we are not local dev   → mock, so a deployed build is
 *                                            never a broken-looking shell
 *
 * Only NEXT_PUBLIC_* values live here. Provider credentials (OpenAI, Gemini,
 * Veo, Runway, Seedance, ElevenLabs, music) are server-side only and must
 * never appear in a NEXT_PUBLIC_ variable.
 */
export type AppEnv = 'mock' | 'development' | 'production';

const rawDemo = (process.env.NEXT_PUBLIC_DEMO_MODE ?? '').toLowerCase();
const rawEnv = (process.env.NEXT_PUBLIC_APP_ENV ?? '').toLowerCase() as AppEnv | '';

/** New canonical name; NEXT_PUBLIC_API_URL kept as a legacy alias. */
const configuredApiBase = (process.env.NEXT_PUBLIC_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_URL ?? '')
  .trim()
  .replace(/\/+$/, '');

const isLocalDev = process.env.NODE_ENV === 'development';

function resolveEnv(): AppEnv {
  if (rawDemo === 'true') return 'mock';
  if (rawEnv === 'mock' || rawEnv === 'development' || rawEnv === 'production') return rawEnv;
  if (configuredApiBase) return isLocalDev ? 'development' : 'production';
  // A deployed build with no backend configured must still be demonstrable.
  return isLocalDev ? 'development' : 'mock';
}

export const APP_ENV: AppEnv = resolveEnv();

/** True when the app answers from the demo snapshot instead of a backend. */
export const DEMO_MODE = APP_ENV === 'mock';

/**
 * Backend origin. Empty in mock mode (nothing is called) and empty when the
 * API is served from the same origin behind a proxy — callers build relative
 * URLs from it, so no host or port is ever hardcoded in UI code.
 */
export const API_BASE_URL = DEMO_MODE ? '' : configuredApiBase || (isLocalDev ? 'http://localhost:8000' : '');

export const API_PREFIX = '/api/v1';
export const API_URL = `${API_BASE_URL}${API_PREFIX}`;

/** Absolute URL for a media path returned by the API or the demo snapshot. */
export function resolveMediaUrl(url?: string | null): string | undefined {
  if (!url) return undefined;
  if (url.startsWith('http://') || url.startsWith('https://') || url.startsWith('data:')) return url;
  const path = url.startsWith('/') ? url : `/${url}`;
  // Demo assets ship with the site; API media lives on the backend origin.
  if (DEMO_MODE || path.startsWith('/demo/')) return path;
  return `${API_BASE_URL}${path}`;
}

/** Shown in Settings so it is always obvious which mode the build is in. */
export const RUNTIME_INFO = {
  appEnv: APP_ENV,
  demoMode: DEMO_MODE,
  apiBaseUrl: API_BASE_URL || null,
} as const;
