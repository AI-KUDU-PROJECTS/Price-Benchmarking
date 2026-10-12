import { useEffect, useState } from "react";

interface State<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
}

interface Options {
  /** Keep showing the last result while a new one loads, so filter bars and
   * the search box stay mounted (and keep focus) as the user types. */
  keepPreviousData?: boolean;
}

export function useApi<T>(loader: () => Promise<T>, deps: unknown[], options: Options = {}): State<T> {
  const [state, setState] = useState<State<T>>({ data: null, error: null, loading: true });
  const { keepPreviousData = false } = options;

  useEffect(() => {
    let cancelled = false;
    setState((previous) => ({
      data: keepPreviousData ? previous.data : null,
      error: null,
      loading: true,
    }));
    loader()
      .then((data) => {
        if (!cancelled) setState({ data, error: null, loading: false });
      })
      .catch((error: Error) => {
        if (!cancelled) setState({ data: null, error, loading: false });
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return state;
}
