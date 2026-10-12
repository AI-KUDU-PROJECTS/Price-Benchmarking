import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SearchField } from "./SearchField";

describe("SearchField", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("commits a trimmed query after the typing delay", () => {
    const onCommit = vi.fn();
    render(
      <SearchField
        label="Search products"
        placeholder="Search products"
        defaultValue=""
        onCommit={onCommit}
      />,
    );

    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "  chicken  " } });
    expect(onCommit).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(300));
    expect(onCommit).toHaveBeenCalledOnce();
    expect(onCommit).toHaveBeenCalledWith("chicken");
  });

  it("commits immediately with Enter or the search button without duplicates", () => {
    const onCommit = vi.fn();
    render(
      <SearchField
        label="Search products"
        placeholder="Search products"
        defaultValue=""
        onCommit={onCommit}
      />,
    );

    const input = screen.getByRole("searchbox");
    fireEvent.change(input, { target: { value: "meal" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "Submit search" }));

    expect(onCommit).toHaveBeenCalledOnce();
    expect(onCommit).toHaveBeenCalledWith("meal");
  });

  it("syncs the displayed query when URL state changes", () => {
    const onCommit = vi.fn();
    const { rerender } = render(
      <SearchField
        label="Search products"
        placeholder="Search products"
        defaultValue="old"
        onCommit={onCommit}
      />,
    );

    rerender(
      <SearchField
        label="Search products"
        placeholder="Search products"
        defaultValue="new"
        onCommit={onCommit}
      />,
    );

    expect((screen.getByRole("searchbox") as HTMLInputElement).value).toBe("new");
    expect(onCommit).not.toHaveBeenCalled();
  });
});
