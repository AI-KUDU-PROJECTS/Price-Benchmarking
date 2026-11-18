import { useEffect, useRef, useState } from "react";

interface State<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
}

interface Options {
  /** Keep this page's result while its filters change. */
  keepPreviousData?: boolean;
  /** Validate open price views every five seconds and when the tab returns. */
  live?: boolean;
}

export function useApi<T>(loader: () => Promise<T>, deps: unknown[], options: Options = {}): State<T> {
  const [state, setState] = useState<State<T>>({ data: null, error: null, loading: true });
  const { keepPreviousData = false, live = false } = options;
  const latestLoader = useRef(loader);
  latestLoader.current = loader;

  useEffect(() => {
    let cancelled = false;
    let busy = false;
    async function load(background = false) {
      if (cancelled || busy) return;
      busy = true;
      if (!background) setState((previous) => ({
        data: keepPreviousData ? previous.data : null, error: null, loading: true,
      }));
      try {
        const data = await latestLoader.current();
        if (!cancelled) setState({ data, error: null, loading: false });
      } catch (error) {
        // No silent fallback to old prices if checking for updates fails.
        if (!cancelled) setState({ data: null, error: error as Error, loading: false });
      } finally {
        busy = false;
      }
    }
    void load();
    const refresh = () => {
      if (document.visibilityState !== "hidden") void load(true);
    };
    const expired = () => {
      cancelled = true;
      setState({ data: null, error: null, loading: true });
    };
    const timer = live ? window.setInterval(refresh, 5_000) : undefined;
    if (live) {
      window.addEventListener("focus", refresh);
      window.addEventListener("pageshow", refresh);
      document.addEventListener("visibilitychange", refresh);
      window.addEventListener("kudu:session-expired", expired);
    }
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearInterval(timer);
      window.removeEventListener("focus", refresh);
      window.removeEventListener("pageshow", refresh);
      document.removeEventListener("visibilitychange", refresh);
      window.removeEventListener("kudu:session-expired", expired);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, live]);

  return state;
}
