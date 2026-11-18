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

it("updates an open page without a loading flash and removes stale data on failure", async () => {
  const { act } = await import("@testing-library/react");
  const { vi } = await import("vitest");
  vi.useFakeTimers();
  try {
    let price = 20;
    let fail = false;
    const loader = vi.fn(async () => {
      if (fail) throw new Error("Unable to verify current prices");
      return price;
    });
    const { result, unmount } = renderHook(() => useApi(loader, [], { live: true }));
    await act(async () => {});
    expect(result.current.data).toBe(20);
    price = 25;
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    expect(result.current.data).toBe(25);
    expect(result.current.loading).toBe(false);
    fail = true;
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    expect(result.current.data).toBeNull();
    expect(result.current.error?.message).toContain("verify current prices");
    unmount();
    const calls = loader.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(loader).toHaveBeenCalledTimes(calls);
  } finally { vi.useRealTimers(); }
});

it("refreshes when a tab returns and ignores a late reply after session expiry", async () => {
  const { act } = await import("@testing-library/react");
  const { vi } = await import("vitest");
  const reply = deferred<number>();
  const loader = vi.fn().mockResolvedValueOnce(20).mockReturnValueOnce(reply.promise);
  const { result } = renderHook(() => useApi(loader, [], { live: true }));
  await waitFor(() => expect(result.current.data).toBe(20));
  act(() => window.dispatchEvent(new Event("focus")));
  expect(loader).toHaveBeenCalledTimes(2);
  act(() => window.dispatchEvent(new Event("kudu:session-expired")));
  await act(async () => reply.resolve(25));
  expect(result.current.data).toBeNull();
});
