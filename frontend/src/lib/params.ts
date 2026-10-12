/** Shared helper for the filter bars on index pages: sets or clears one
 * query param while preserving the rest, and drops the page's own param
 * mutations back into the router's search params. Changing any filter
 * returns the list to its first page. */
export function setSearchParam(
  setParams: (params: URLSearchParams) => void,
  params: URLSearchParams,
  key: string,
  value: string,
) {
  const next = new URLSearchParams(params);
  if (value) next.set(key, value);
  else next.delete(key);
  if (key !== "page") next.delete("page");
  setParams(next);
}

/** Clears only the given filter keys (and the page), leaving any other
 * query params intact. */
export function clearSearchParams(
  setParams: (params: URLSearchParams) => void,
  params: URLSearchParams,
  keys: readonly string[],
) {
  const next = new URLSearchParams(params);
  for (const key of keys) next.delete(key);
  next.delete("page");
  setParams(next);
}

/** Moves a paged list to `page`; page 1 keeps the URL clean. */
export function setPageParam(
  setParams: (params: URLSearchParams) => void,
  params: URLSearchParams,
  page: number,
) {
  setSearchParam(setParams, params, "page", page > 1 ? String(page) : "");
}
