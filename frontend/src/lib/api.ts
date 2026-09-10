'use client';

/**
 * Typed API client.
 *
 * Every failure is converted into an `ApiError` carrying the backend's
 * bilingual message, so screens can show a friendly state instead of a stack
 * trace. Secrets never live here — the browser only talks to our own API.
 */
export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
export const API_URL = `${API_BASE}/api/v1`;

export class ApiError extends Error {
  code: string;
  messageAr: string;
  status: number;
  extra: Record<string, unknown>;

  constructor(status: number, code: string, message: string, messageAr: string, extra: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.messageAr = messageAr;
    this.extra = extra;
  }

  get isOffline() {
    return this.code === 'network_error';
  }
}

function authHeaders(): Record<string, string> {
  try {
    const token = window.localStorage.getItem('adflow.token');
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    return {};
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: {
        ...(init.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
        ...authHeaders(),
        ...(init.headers ?? {}),
      },
      cache: 'no-store',
    });
  } catch {
    throw new ApiError(0, 'network_error', 'Cannot reach the AdFlow API.', 'ما نكدر نوصل لسيرفر أدفلو.');
  }

  if (response.status === 204) return undefined as T;

  let payload: any = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok) {
    const error = payload?.error ?? {};
    throw new ApiError(
      response.status,
      error.code ?? 'http_error',
      error.message ?? payload?.detail?.[0]?.msg ?? `Request failed (${response.status})`,
      error.message_ar ?? 'صار خطأ بالطلب.',
      error,
    );
  }
  return payload as T;
}

export const api = {
  get: <T,>(path: string) => request<T>(path),
  post: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body === undefined ? '{}' : JSON.stringify(body) }),
  patch: <T,>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PATCH', body: JSON.stringify(body ?? {}) }),
  delete: <T,>(path: string) => request<T>(path, { method: 'DELETE' }),
  upload: <T,>(path: string, form: FormData) => request<T>(path, { method: 'POST', body: form }),
};

/** Turn a relative media path from the API into an absolute browser URL. */
export function mediaUrl(url?: string | null): string | undefined {
  if (!url) return undefined;
  if (url.startsWith('http')) return url;
  return `${API_BASE}${url.startsWith('/') ? '' : '/'}${url}`;
}
