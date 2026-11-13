import { useCallback, useEffect, useRef, useState } from "react";
import { getJson } from "./api";

export type Loadable<T> = { data: T | null; error: string | null; loading: boolean; reload: () => void };

/** Fetch JSON from the API with loading / error state, abort on unmount, optional polling. */
export function useApi<T>(path: string | null, pollMs?: number): Loadable<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(path != null);
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (path == null) return;
    const ctl = new AbortController();
    setLoading(true);
    getJson<T>(path, ctl.signal)
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e: unknown) => {
        if (ctl.signal.aborted) return;
        setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!ctl.signal.aborted) setLoading(false);
      });
    return () => ctl.abort();
  }, [path, tick]);

  useEffect(() => {
    if (!pollMs || path == null) return;
    const id = window.setInterval(reload, pollMs);
    return () => window.clearInterval(id);
  }, [pollMs, path, reload]);

  return { data, error, loading, reload };
}

/** Width of an element, for responsive chart sizing decisions. */
export function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T | null>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((e) => setW(e[0].contentRect.width));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}
