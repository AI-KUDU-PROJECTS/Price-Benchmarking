import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useApi } from "./useApi";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

describe("useApi", () => {
  it("keeps the last result while a new query loads when asked", async () => {
    const first = deferred<string>();
    const second = deferred<string>();
    const loads = { zin: first.promise, zinger: second.promise } as Record<string, Promise<string>>;
    const { result, rerender } = renderHook(
      ({ query }) => useApi(() => loads[query], [query], { keepPreviousData: true }),
      { initialProps: { query: "zin" } },
    );

    first.resolve("zin results");
    await waitFor(() => expect(result.current.data).toBe("zin results"));

    rerender({ query: "zinger" });
    expect(result.current.loading).toBe(true);
    expect(result.current.data).toBe("zin results");

    second.resolve("zinger results");
    await waitFor(() => expect(result.current.data).toBe("zinger results"));
    expect(result.current.loading).toBe(false);
  });

  it("clears the result between queries by default", async () => {
    const first = deferred<string>();
    const loads = { a: first.promise, b: new Promise<string>(() => undefined) } as Record<string, Promise<string>>;
    const { result, rerender } = renderHook(({ key }) => useApi(() => loads[key], [key]), {
      initialProps: { key: "a" },
    });
    first.resolve("a");
    await waitFor(() => expect(result.current.data).toBe("a"));

    rerender({ key: "b" });
    expect(result.current.data).toBeNull();
    expect(result.current.loading).toBe(true);
  });
});
