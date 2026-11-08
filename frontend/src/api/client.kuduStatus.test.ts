import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./client";
import type { CollectionRun, PullRun } from "./types";

function batch(): PullRun {
  return {
    runId: "scheduled-run", status: "partial", trigger: "scheduled",
    startedAt: "2026-11-04T10:00:00Z", completedAt: "2026-11-04T10:30:00Z",
    brands: [
      { id: "kudu", name: "KUDU", status: "failed", startedAt: "2026-11-04T10:00:00Z",
        completedAt: "2026-11-04T10:00:54Z", message: "AUTH_FAILED" },
      { id: "kfc", name: "KFC", status: "success", startedAt: "2026-11-04T10:01:00Z",
        completedAt: "2026-11-04T10:30:00Z", message: "Collected 103 products." },
    ],
  };
}
function menu(): CollectionRun {
  return {
    id: "new-kudu-menu", brandId: "kudu", channel: "hungerstation", status: "success",
    startedAt: "2026-11-04T13:15:02+03:00", completedAt: "2026-11-04T13:15:02+03:00",
    itemCount: 143, warningCount: null, errorSummary: null, location: "HungerStation",
  };
}
function mockRequests(current: PullRun, saved = menu(), failOverview = false) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.endsWith("/market/hungerstation/pull")) return { ok: true, json: async () => ({ run: current }) };
    expect(url).toBe("/api/v1/brands/kudu/overview");
    if (failOverview) throw new Error("Unavailable");
    return { ok: true, json: async () => ({ runs: [saved] }) };
  }));
}
afterEach(() => vi.unstubAllGlobals());

describe("KUDU status displayed from the latest menu", () => {
  it("replaces an old authentication failure using the real newer result", async () => {
    const current = batch();
    mockRequests(current);
    const { run } = await api.hungerstationPullStatus();
    expect(run?.status).toBe("success");
    expect(run?.view).toBe("latest_results");
    expect(run?.completedAt).toBe(current.completedAt);
    expect(run?.brands[0]).toMatchObject({ status: "success", completedAt: menu().completedAt });
    expect(run?.brands[0].message).toContain("143 products");
    expect(current.brands[0].status).toBe("failed");
  });
  it("preserves other active restaurants and the running batch identity", async () => {
    const current = batch();
    current.status = "running";
    current.completedAt = null;
    current.brands[1].status = "running";
    current.brands[1].completedAt = null;
    mockRequests(current);
    const { run } = await api.hungerstationPullStatus();
    expect(run).toMatchObject({ status: "running", runId: current.runId, completedAt: null });
    expect(run?.brands[0].status).toBe("success");
    expect(run?.brands[1]).toEqual(current.brands[1]);
  });
  it.each(["pending", "running"] as const)("does not replace KUDU while %s", async (status) => {
    const current = batch();
    current.brands[0].status = status;
    mockRequests(current);
    expect((await api.hungerstationPullStatus()).run).toEqual(current);
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it.each([
    { startedAt: "2026-11-04T09:00:00Z" },
    { startedAt: "2026-11-04T10:00:54Z" },
    { channel: "delivery" as const },
    { itemCount: 0 },
    { status: "failed" as const },
  ])("does not hide a failure with an inapplicable result: %j", async (changes) => {
    const current = batch();
    mockRequests(current, { ...menu(), ...changes });
    expect((await api.hungerstationPullStatus()).run).toEqual(current);
  });
  it("still displays batch results if the menu lookup fails", async () => {
    const current = batch();
    mockRequests(current, menu(), true);
    expect((await api.hungerstationPullStatus()).run).toEqual(current);
  });
});
