import { describe, expect, it, vi } from "vitest";
import { ReadCache } from "./readCache";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

describe("validated price cache", () => {
  it("validates every reuse and fetches new prices immediately when the version changes", async () => {
    let revision = "one";
    const version = vi.fn(async () => revision);
    const load = vi.fn(async () => ({ data: { price: revision === "one" ? 20 : 25 }, version: revision }));
    const cache = new ReadCache(version);
    const first = await cache.read("kfc/pickup", load);
    first.price = 999;
    expect(await cache.read("kfc/pickup", load)).toEqual({ price: 20 });
    expect(load).toHaveBeenCalledTimes(1);
    expect(version).toHaveBeenCalledTimes(1);
    revision = "two";
    expect(await cache.read("kfc/pickup", load)).toEqual({ price: 25 });
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("keeps restaurants, channels, filters and pages separate", async () => {
    const cache = new ReadCache(async () => "v1");
    const keys = ["kfc/menu?channel=pickup", "kfc/menu?channel=delivery", "herfy/menu", "kfc/menu?q=burger", "kfc/menu?page=2"];
    for (const key of keys) await cache.read(key, async () => ({ data: key, version: "v1" }));
    const wrong = vi.fn();
    for (const key of keys) expect(await cache.read(key, wrong)).toBe(key);
    expect(wrong).not.toHaveBeenCalled();
  });

  it("coalesces simultaneous requests and simultaneous version checks", async () => {
    const revision = deferred<string>();
    const version = vi.fn(() => revision.promise);
    const cache = new ReadCache(version);
    const load = vi.fn(async () => ({ data: { price: 20 }, version: "v1" }));
    await Promise.all([cache.read("a", load), cache.read("a", load)]);
    expect(load).toHaveBeenCalledTimes(1);
    await cache.read("b", load);
    const reads = [cache.read("a", load), cache.read("b", load)];
    revision.resolve("v1");
    await Promise.all(reads);
    expect(version).toHaveBeenCalledTimes(1);
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("does not return stale data when validation fails, and can recover", async () => {
    const version = vi.fn(async (): Promise<string> => { throw new Error("Offline"); });
    const cache = new ReadCache(version);
    const load = vi.fn(async () => ({ data: 20, version: "v1" }));
    await cache.read("a", load);
    await expect(cache.read("a", load)).rejects.toThrow("Offline");
    expect(await cache.read("a", load)).toBe(20);
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("does not retain unversioned responses or data beyond its TTL", async () => {
    let now = 0;
    const cache = new ReadCache(async () => "v1", () => now, 30);
    const load = vi.fn(async () => ({ data: 20, version: "v1" }));
    await cache.read("a", load);
    now = 30;
    await cache.read("a", load);
    expect(load).toHaveBeenCalledTimes(2);
    const unknown = vi.fn(async () => ({ data: 30, version: null }));
    await cache.read("b", unknown);
    await cache.read("b", unknown);
    expect(unknown).toHaveBeenCalledTimes(2);
  });

  it("clears every page and rejects in-flight data when the session ends", async () => {
    const cache = new ReadCache(async () => "v1");
    const response = deferred<{ data: number; version: string }>();
    const pending = cache.read("a", () => response.promise);
    cache.clear();
    response.resolve({ data: 20, version: "v1" });
    await expect(pending).rejects.toThrow("session changed");
    expect(await cache.read("a", async () => ({ data: 30, version: "v1" }))).toBe(30);
  });

  it("rejects a late validation response after logout", async () => {
    const response = deferred<string>();
    const cache = new ReadCache(() => response.promise);
    const load = async () => ({ data: 20, version: "v1" });
    await cache.read("a", load);
    const pending = cache.read("a", load);
    cache.clear();
    response.resolve("v1");
    await expect(pending).rejects.toThrow("session changed");
  });

  it("does not restore a slower old response after discovering a new version", async () => {
    const cache = new ReadCache(async () => "v2");
    await cache.read("other", async () => ({ data: 30, version: "v2" }));
    const old = deferred<{ data: number; version: string }>();
    const load = vi.fn().mockReturnValueOnce(old.promise).mockResolvedValue({ data: 25, version: "v2" });
    const pending = cache.read("menu", load);
    await cache.read("other", async () => ({ data: 30, version: "v2" }));
    old.resolve({ data: 20, version: "v1" });
    expect(await pending).toBe(25);
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("bounds memory and evicts least recently used responses", async () => {
    const cache = new ReadCache(async () => "v1", undefined, 30_000, 2, 100);
    const load = vi.fn(async () => ({ data: "price", version: "v1" }));
    await cache.read("a", load); await cache.read("b", load);
    await cache.read("a", load); await cache.read("c", load);
    await cache.read("b", load);
    expect(load).toHaveBeenCalledTimes(4);
  });
});
