import { useCallback, useEffect, useRef, useState } from "react";

export interface Async<T> {
  data: T | undefined;
  error: unknown;
  loading: boolean;
  reload: () => Promise<void>;
  setData: (d: T) => void;
}

/** Fetch on mount / deps change; optional polling interval (ms) that pauses while the tab is hidden. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[], pollMs?: number | null): Async<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const alive = useRef(true);
  const seq = useRef(0);

  const reload = useCallback(async () => {
    const my = ++seq.current;
    try {
      const d = await fnRef.current();
      if (alive.current && my === seq.current) {
        setData(d);
        setError(null);
      }
    } catch (e) {
      if (alive.current && my === seq.current) setError(e);
    } finally {
      if (alive.current && my === seq.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    setLoading(true);
    void reload();
    return () => {
      alive.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    if (!pollMs) return;
    const id = window.setInterval(() => {
      if (!document.hidden) void reload();
    }, pollMs);
    const onVis = () => {
      if (!document.hidden) void reload();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [pollMs, reload]);

  return { data, error, loading, reload, setData };
}

export function useReducedMotion(): boolean {
  const [r, setR] = useState(() => typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches);
  useEffect(() => {
    const m = matchMedia("(prefers-reduced-motion: reduce)");
    const f = () => setR(m.matches);
    m.addEventListener("change", f);
    return () => m.removeEventListener("change", f);
  }, []);
  return r;
}

export function useNow(ms = 1000): number {
  const [n, setN] = useState(Date.now());
  useEffect(() => {
    const id = setInterval(() => setN(Date.now()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return n;
}

export function usePageVisible(): boolean {
  const [v, setV] = useState(!document.hidden);
  useEffect(() => {
    const f = () => setV(!document.hidden);
    document.addEventListener("visibilitychange", f);
    return () => document.removeEventListener("visibilitychange", f);
  }, []);
  return v;
}

export function useTitle(title: string) {
  useEffect(() => {
    document.title = title ? `${title} · BlockID` : "BlockID Business Passport";
  }, [title]);
}
