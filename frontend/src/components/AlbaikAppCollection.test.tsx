import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { PullRun } from "../api/types";
import { AlbaikAppCollection, AlbaikAppCollectionButton, useAlbaikAppCollection } from "./AlbaikAppCollection";

vi.mock("../api/client", () => ({ api: { albaikAppPullStatus: vi.fn(), startAlbaikAppPull: vi.fn() } }));

function Collection({ onComplete }: { onComplete: () => void }) {
  const collection = useAlbaikAppCollection(onComplete);
  return <><AlbaikAppCollectionButton collection={collection} /><AlbaikAppCollection collection={collection} /></>;
}

function run(status: PullRun["status"]): PullRun {
  return { runId: "app-run", status, startedAt: "2026-11-02T07:00:00Z", completedAt: null,
    brands: [
      { id: "albaik-pickup", name: "AlBaik · Pickup", status: status === "running" ? "running" : "success", startedAt: null, completedAt: null, message: status === "running" ? null : "Collected 90 products; 4 new images saved." },
      { id: "albaik-delivery", name: "AlBaik · Delivery", status: status === "running" ? "pending" : "failed", startedAt: null, completedAt: null, message: status === "running" ? null : "DELIVERY_UNAVAILABLE: No delivery coverage. Previous complete data kept." },
    ] };
}

describe("Albaik app collection", () => {
  beforeEach(() => { vi.useFakeTimers(); vi.clearAllMocks(); });
  afterEach(() => { vi.useRealTimers(); });

  it("shows each channel's result and failure reason independently", async () => {
    vi.mocked(api.albaikAppPullStatus).mockResolvedValue({ run: run("partial") });
    await act(async () => { render(<Collection onComplete={vi.fn()} />); });
    expect(screen.getByText("AlBaik · Pickup")).toBeTruthy();
    expect(screen.getByText("AlBaik · Delivery")).toBeTruthy();
    expect(screen.getByText("Collected 90 products; 4 new images saved.")).toBeTruthy();
    expect(screen.getByText(/DELIVERY_UNAVAILABLE/)).toBeTruthy();
  });

  it("prevents a duplicate start and refreshes market data when a fast run finishes", async () => {
    vi.mocked(api.albaikAppPullStatus).mockResolvedValue({ run: null });
    vi.mocked(api.startAlbaikAppPull).mockResolvedValue({ run: run("running"), started: true });
    const completed = vi.fn();
    await act(async () => { render(<Collection onComplete={completed} />); });
    const button = screen.getByRole("button", { name: "Collect Albaik app" }) as HTMLButtonElement;
    await act(async () => { fireEvent.click(button); });
    expect(button.disabled).toBe(true);
    vi.mocked(api.albaikAppPullStatus).mockResolvedValue({ run: run("partial") });
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(completed).toHaveBeenCalledTimes(1);
    expect(button.disabled).toBe(false);
    expect(api.startAlbaikAppPull).toHaveBeenCalledTimes(1);
  });
});
