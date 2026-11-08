import { act, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PullRun } from "../api/types";

const apiMock = vi.hoisted(() => ({
  marketOverview: vi.fn(), pullStatus: vi.fn(), hungerstationPullStatus: vi.fn(),
  pullSchedule: vi.fn(), albaikAppPullStatus: vi.fn(),
}));
vi.mock("../api/client", () => ({ api: apiMock, ApiError: class extends Error {} }));

import { MarketOverviewPage } from "./MarketOverviewPage";

function run(recovered = false): PullRun {
  return {
    runId: recovered ? "latest-results" : "scheduled-batch",
    status: recovered ? "success" : "failed", trigger: recovered ? undefined : "scheduled",
    view: recovered ? "latest_results" : undefined,
    startedAt: "2026-11-03T10:00:00Z", completedAt: recovered ? "2026-11-03T14:10:37Z" : "2026-11-03T10:30:00Z",
    brands: [
      { id: "burger-king", name: "Burger King", status: recovered ? "success" : "failed",
        startedAt: "2026-11-03T14:03:46Z", completedAt: "2026-11-03T14:10:37Z",
        message: recovered ? "Collected 166 products from HungerStation. Updated by a newer collection." : "AI_ACTION_LIMIT" },
      { id: "albaik", name: "AlBaik", status: recovered ? "success" : "failed",
        startedAt: "2026-11-03T13:55:45Z", completedAt: "2026-11-03T13:59:14Z",
        message: recovered ? "Collected 74 products from HungerStation. Updated by a newer collection." : "AI_ACTION_LIMIT" },
    ],
  };
}

describe("HungerStation latest collection status", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    apiMock.marketOverview.mockResolvedValue({
      freshness: "fresh", lastUpdatedAt: "2026-11-03T14:10:37Z", brands: [],
      connectedBrandIds: [], highlights: [],
      counts: { priceDecreases: 0, priceIncreases: 0, newProducts: 0, newOffers: 0, endedOffers: 0 },
    });
    apiMock.pullStatus.mockResolvedValue({ run: null });
    apiMock.albaikAppPullStatus.mockResolvedValue({ run: null });
    apiMock.pullSchedule.mockResolvedValue(null);
  });
  afterEach(() => vi.useRealTimers());

  it("shows latest successes with real dates instead of calling them the old automatic run", async () => {
    apiMock.hungerstationPullStatus.mockResolvedValue({ run: run(true) });
    await act(async () => { render(<MemoryRouter><MarketOverviewPage /></MemoryRouter>); });
    const panel = within(screen.getByRole("region", { name: "HungerStation collection progress" }));
    expect(panel.getByText(/Latest result per restaurant/)).toBeTruthy();
    expect(panel.queryByText(/Automatic run/)).toBeNull();
    expect(panel.queryByText("failed")).toBeNull();
    expect(panel.getByText(/Collected 166 products/)).toBeTruthy();
    expect(panel.getByText(/Collected 74 products/)).toBeTruthy();
    expect(panel.getAllByText("success")).toHaveLength(3);
    expect(panel.getByText("2026-11-03 05:10 pm")).toBeTruthy();
  });

  it("refreshes an idle failed table when an individual collection succeeds", async () => {
    apiMock.hungerstationPullStatus.mockResolvedValue({ run: run() });
    await act(async () => { render(<MemoryRouter><MarketOverviewPage /></MemoryRouter>); });
    expect(screen.getAllByText("failed")).toHaveLength(3);
    apiMock.hungerstationPullStatus.mockResolvedValue({ run: run(true) });
    await act(async () => { await vi.advanceTimersByTimeAsync(15000); });
    expect(screen.queryByText("failed")).toBeNull();
    expect(screen.getByText(/Collected 166 products/)).toBeTruthy();
    expect(apiMock.marketOverview).toHaveBeenCalledTimes(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(15000); });
    expect(apiMock.marketOverview).toHaveBeenCalledTimes(2);
  });

  it("keeps active collection progress and disables duplicate starts", async () => {
    const active = { ...run(), status: "running" as const, completedAt: null };
    apiMock.hungerstationPullStatus.mockResolvedValue({ run: active });
    await act(async () => { render(<MemoryRouter><MarketOverviewPage /></MemoryRouter>); });
    expect((screen.getByRole("button", { name: "Collect HungerStation" }) as HTMLButtonElement).disabled).toBe(true);
    apiMock.hungerstationPullStatus.mockResolvedValue({ run: run(true) });
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect((screen.getByRole("button", { name: "Collect HungerStation" }) as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByText(/Latest result per restaurant/)).toBeTruthy();
  });
});
