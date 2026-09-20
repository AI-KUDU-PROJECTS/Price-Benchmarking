/** Shared helper for the filter bars on index pages: sets or clears one
 * query param while preserving the rest, and drops the page's own param
 * mutations back into the router's search params. */
export function setSearchParam(
  setParams: (params: URLSearchParams) => void,
  params: URLSearchParams,
  key: string,
  value: string,
) {
  const next = new URLSearchParams(params);
  if (value) next.set(key, value);
  else next.delete(key);
  setParams(next);
}

/** Clears only the given filter keys, leaving any other query params intact. */
export function clearSearchParams(
  setParams: (params: URLSearchParams) => void,
  params: URLSearchParams,
  keys: readonly string[],
) {
  const next = new URLSearchParams(params);
  for (const key of keys) next.delete(key);
  setParams(next);
}
