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

/**
 * A workflow stage that runs as a background job.
 *
 * Analysis, concepts, script and storyboard each call the model, which takes
 * far longer than an HTTP request may live: the first real deploy showed a
 * 42-second `POST /analysis/run` dying with "cannot reach the server" and
 * taking the unfinished analysis with it. Those endpoints now queue and
 * return immediately, and the matching GET carries the job — so every one of
 * those screens polls, and they all do it the same way here.
 */
export type StageJob = {
  id: string;
  job_type: string;
  status: 'queued' | 'running' | 'retrying' | 'completed' | 'failed' | 'cancelled';
  progress: number | null;
  progress_label: string | null;
  error_message: string | null;
};

export const JOB_IN_FLIGHT = ['queued', 'running', 'retrying'];

/**
 * Fetch a stage endpoint, polling only while its job is unfinished.
 *
 * `onSettled` fires once per job, when it stops being in flight — that is
 * where a page refreshes the project header, whose state the job moved.
 */
export function useStageJob<T extends { job?: StageJob | null }>(path: string, onSettled?: () => void) {
  const [status, setStatus] = useState<string | null>(null);
  const working = status !== null && JOB_IN_FLIGHT.includes(status);
  const result = useApi<T>(path, { pollMs: working ? 1500 : undefined });
  const job = result.data?.job ?? null;

  const previous = useRef<string | null>(null);
  useEffect(() => {
    const next = job?.status ?? null;
    setStatus(next);
    const settled = next === 'completed' || next === 'failed';
    if (settled && previous.current && JOB_IN_FLIGHT.includes(previous.current)) onSettled?.();
    previous.current = next;
  }, [job?.status, onSettled]);

  return { ...result, job, working };
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
