import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ListMeta } from "../api/types";
import { clearSearchParams, setPageParam, setSearchParam } from "../lib/params";
import { Pager } from "./Pager";

function meta(page: number, total: number): ListMeta {
  return {
    page,
    pageSize: 200,
    total,
    freshness: "fresh",
    sourceRunIds: [],
    generatedAt: "2026-10-12T10:00:00+03:00",
    timezone: "Asia/Riyadh",
  };
}

describe("Pager", () => {
  it("stays hidden when one page holds every item", () => {
    const { container } = render(<Pager meta={meta(1, 200)} onPage={vi.fn()} />);
    expect(container.innerHTML).toBe("");
  });

  it("shows the range and moves between pages", () => {
    window.scrollTo = vi.fn();
    const onPage = vi.fn();
    const { rerender } = render(<Pager meta={meta(1, 374)} onPage={onPage} />);

    expect(screen.getByText("Showing 1–200 of 374")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Previous" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(onPage).toHaveBeenCalledWith(2);

    rerender(<Pager meta={meta(2, 374)} onPage={onPage} />);
    expect(screen.getByText("Showing 201–374 of 374")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("page param", () => {
  it("returns to the first page whenever a filter changes", () => {
    const setParams = vi.fn();
    setSearchParam(setParams, new URLSearchParams("channel=pickup&page=2"), "q", "zinger");
    expect(setParams.mock.calls[0][0].toString()).toBe("channel=pickup&q=zinger");

    clearSearchParams(setParams, new URLSearchParams("q=zinger&page=3&tab=x"), ["q"]);
    expect(setParams.mock.calls[1][0].toString()).toBe("tab=x");
  });

  it("keeps page 1 out of the URL", () => {
    const setParams = vi.fn();
    setPageParam(setParams, new URLSearchParams("q=zinger"), 2);
    expect(setParams.mock.calls[0][0].toString()).toBe("q=zinger&page=2");
    setPageParam(setParams, new URLSearchParams("q=zinger&page=2"), 1);
    expect(setParams.mock.calls[1][0].toString()).toBe("q=zinger");
  });
});
