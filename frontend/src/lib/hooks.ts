'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { ApiError, api } from './api';

type State<T> = { data: T | null; error: ApiError | null; loading: boolean };

/** Small data-fetching hook with refresh + optional polling. */
export function useApi<T>(path: string | null, options: { pollMs?: number; enabled?: boolean } = {}) {
  const { pollMs, enabled = true } = options;
  const [state, setState] = useState<State<T>>({ data: null, error: null, loading: Boolean(path && enabled) });
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const load = useCallback(
    async (silent = false) => {
      if (!path || !enabled) return;
      if (!silent) setState((s) => ({ ...s, loading: true }));
      try {
        const data = await api.get<T>(path);
        if (mounted.current) setState({ data, error: null, loading: false });
      } catch (error) {
        if (mounted.current) setState((s) => ({ data: s.data, error: error as ApiError, loading: false }));
      }
    },
    [path, enabled],
  );

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!pollMs || !path || !enabled) return;
    const timer = setInterval(() => load(true), pollMs);
    return () => clearInterval(timer);
  }, [pollMs, path, enabled, load]);

  return { ...state, reload: load, setData: (data: T) => setState({ data, error: null, loading: false }) };
}

/** Wrap a mutation so screens get consistent pending/error handling. */
export function useMutation<TArgs extends any[], TResult>(fn: (...args: TArgs) => Promise<TResult>) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const run = useCallback(
    async (...args: TArgs): Promise<TResult | null> => {
      setPending(true);
      setError(null);
      try {
        return await fn(...args);
      } catch (err) {
        setError(err as ApiError);
        return null;
      } finally {
        setPending(false);
      }
    },
    [fn],
  );

  return { run, pending, error, clearError: () => setError(null) };
}

/** Persisted boolean (Director Mode, panel state, …). */
export function useLocalToggle(key: string, initial = false) {
  const [value, setValue] = useState(initial);
  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(key);
      if (stored !== null) setValue(stored === 'true');
    } catch {
      /* ignore */
    }
  }, [key]);
  const update = useCallback(
    (next: boolean) => {
      setValue(next);
      try {
        window.localStorage.setItem(key, String(next));
      } catch {
        /* ignore */
      }
    },
    [key],
  );
  return [value, update] as const;
}
