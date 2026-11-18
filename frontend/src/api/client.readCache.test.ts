import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "./client";

const fetchMock = vi.fn();
const reply = (body: unknown, version: string | null = null, status = 200) => ({
  ok: status === 200, status, statusText: "", json: async () => body,
  headers: new Headers(version ? { "X-Data-Version": version } : {}),
});
beforeEach(() => {
  window.dispatchEvent(new Event("kudu:session-expired"));
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => { vi.unstubAllGlobals(); });

it("checks the server version before returning a saved menu and downloads a changed menu", async () => {
  fetchMock.mockResolvedValueOnce(reply({ items: [{ price: 20 }] }, "v1"));
  await api.menu("kfc");
  fetchMock.mockResolvedValueOnce(reply({ version: "v1" }));
  expect(await api.menu("kfc")).toEqual({ items: [{ price: 20 }] });
  expect(fetchMock.mock.calls.map(call => call[0])).toEqual(["/api/v1/brands/kfc/menu", "/api/v1/data-version"]);
  fetchMock.mockResolvedValueOnce(reply({ version: "v2" }))
    .mockResolvedValueOnce(reply({ items: [{ price: 25 }] }, "v2"));
  expect(await api.menu("kfc")).toEqual({ items: [{ price: 25 }] });
});

it("retries when a collection commits during the server read", async () => {
  fetchMock.mockResolvedValueOnce(reply({ detail: { error: "data_changed_during_read" } }, null, 409))
    .mockResolvedValueOnce(reply({ items: [{ price: 25 }] }, "v2"));
  expect(await api.menu("kfc")).toEqual({ items: [{ price: 25 }] });
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

it("rejects cached data after authentication expires and clears all saved pages", async () => {
  fetchMock.mockResolvedValueOnce(reply({ items: [] }, "v1"));
  await api.menu("kfc");
  fetchMock.mockResolvedValueOnce(reply({ detail: "Sign in" }, null, 401));
  await expect(api.menu("kfc")).rejects.toThrow();
  fetchMock.mockResolvedValueOnce(reply({ items: [{ price: 30 }] }, "v1"));
  expect(await api.menu("kfc")).toEqual({ items: [{ price: 30 }] });
  expect(fetchMock.mock.calls[2][0]).toBe("/api/v1/brands/kfc/menu");
});

it("does not keep another restaurant cached after a 401 response", async () => {
  fetchMock.mockResolvedValueOnce(reply({ items: [] }, "v1"))
    .mockResolvedValueOnce(reply({ items: [] }, "v1"));
  await api.menu("kfc"); await api.menu("herfy");
  fetchMock.mockResolvedValueOnce(reply({ detail: "Sign in" }, null, 401));
  await expect(api.menu("kfc")).rejects.toThrow();
  fetchMock.mockResolvedValueOnce(reply({ items: [] }, "v1"));
  await api.menu("herfy");
  expect(fetchMock.mock.calls[3][0]).toBe("/api/v1/brands/herfy/menu");
});
