import { render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Channel, ListResponse, MenuRow, Product } from "../api/types";

const apiMock = vi.hoisted(() => ({ menu: vi.fn() }));
vi.mock("../api/client", () => ({ api: apiMock, ApiError: class extends Error {} }));
import { BrandMenuPage } from "./BrandMenuPage";

function product(channel: Channel, price: number | null, changes: Partial<Product> = {}): Product {
  return {
    id: `${channel}-burger`, brandId: "kfc", sourceId: "burger", nameEn: "Chicken Burger",
    nameAr: "برجر دجاج", category: "Burgers", categoryAr: null, imageUrl: null, channel,
    location: null, regularPrice: price, specialPrice: null, previousRegularPrice: null,
    previousSpecialPrice: null, currency: "SAR", sizes: [], availability: true,
    isPublished: true, isHidden: false, descriptionAr: null, descriptionEn: null,
    calories: null, status: "active", firstSeenAt: null, lastSeenAt: null,
    observedAt: null, sourceRunId: null, ...changes,
  };
}

function response(channels: MenuRow["channels"], total = 1): ListResponse<MenuRow> {
  const first = Object.values(channels)[0]!;
  return {
    items: [{ id: first.id, product: first, channels }],
    meta: { page: 1, pageSize: 200, total, freshness: "fresh", sourceRunIds: [],
      generatedAt: "2026-11-08T12:00:00+03:00", timezone: "Asia/Riyadh" },
  };
}

function open(brand = "kfc", search = "") {
  return render(<MemoryRouter initialEntries={[`/competitors/${brand}/menu${search}`]}>
    <BrandMenuPage brandId={brand} />
  </MemoryRouter>);
}

beforeEach(() => vi.clearAllMocks());

describe("Menu prices across channels", () => {
  it("shows one row with three channel prices and separate size prices", async () => {
    apiMock.menu.mockResolvedValue(response({
      pickup: product("pickup", 20, { sizes: [{ label: "Large", price: 23, currency: "SAR" }] }),
      delivery: product("delivery", 22),
      hungerstation: product("hungerstation", 27, { specialPrice: 25 }),
    }));
    open();
    const table = await screen.findByRole("table");
    expect((screen.getByRole("combobox", { name: "Channel" }) as HTMLSelectElement).value).toBe("all");
    for (const name of ["Pickup", "Delivery", "HungerStation"]) {
      expect(within(table).getByRole("columnheader", { name })).toBeTruthy();
    }
    expect(within(table).getAllByRole("row")).toHaveLength(2);
    expect(within(table).getAllByText("Chicken Burger")).toHaveLength(1);
    const cells = within(within(table).getAllByRole("row")[1]).getAllByRole("cell");
    expect(cells[3].textContent).toContain("SAR 20.00");
    expect(cells[3].textContent).toContain("Large: SAR 23.00");
    expect(cells[4].textContent).toBe("SAR 22.00");
    expect(cells[5].textContent).toContain("SAR 25.00");
    expect(cells[5].textContent).toContain("Regular SAR 27.00");
    expect(within(table).getByRole("link", { name: "Delivery details for Chicken Burger" }).getAttribute("href"))
      .toBe("/competitors/kfc/products/delivery-burger");
  });

  it("shows a dash for missing prices and channels, while preserving a real zero", async () => {
    apiMock.menu.mockResolvedValue(response({ pickup: product("pickup", 0), delivery: product("delivery", null) }));
    open();
    const cells = within((await screen.findAllByRole("row"))[1]).getAllByRole("cell");
    expect(cells[3].textContent).toBe("SAR 0.00");
    expect(cells[4].textContent).toBe("—");
    expect(cells[5].textContent).toBe("—");
  });

  it("keeps channel availability flags next to the relevant price", async () => {
    apiMock.menu.mockResolvedValue(response({ pickup: product("pickup", 20, { availability: false }),
      delivery: product("delivery", 22) }));
    open();
    const cells = within((await screen.findAllByRole("row"))[1]).getAllByRole("cell");
    expect(within(cells[3]).getByText("unavailable")).toBeTruthy();
    expect(within(cells[4]).queryByText("unavailable")).toBeNull();
  });

  it("preserves the KUDU default channel and switches All channels explicitly", async () => {
    const pickup = product("pickup", 20, { brandId: "kudu" });
    const delivery = product("delivery", 22, { brandId: "kudu" });
    apiMock.menu.mockImplementation(async (_brand: string, query: string) =>
      query.includes("channel=delivery") ? response({ delivery }) : response({ pickup, delivery }));
    open("kudu");
    expect(await screen.findByRole("columnheader", { name: "Price" })).toBeTruthy();
    expect(apiMock.menu).toHaveBeenCalledWith("kudu", "?channel=delivery");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Channel" }), "all");
    await waitFor(() => expect(apiMock.menu).toHaveBeenLastCalledWith("kudu", ""));
    expect(await screen.findByRole("columnheader", { name: "HungerStation" })).toBeTruthy();
    expect((screen.getByRole("combobox") as HTMLSelectElement).value).toBe("all");
  });

  it("resets pagination on a channel change while retaining the search", async () => {
    apiMock.menu.mockImplementation(async (_brand: string, query: string) =>
      query.includes("channel=pickup") ? response({ pickup: product("pickup", 20) })
        : response({ pickup: product("pickup", 20), delivery: product("delivery", 22) }));
    open("kfc", "?q=Chicken&page=2");
    await screen.findByRole("table");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Channel" }), "pickup");
    await waitFor(() => expect(apiMock.menu).toHaveBeenLastCalledWith("kfc", "?channel=pickup&q=Chicken"));
    expect(await screen.findByRole("columnheader", { name: "Current" })).toBeTruthy();
    expect(screen.queryByRole("columnheader", { name: "HungerStation" })).toBeNull();
  });

  it("pages by grouped products without losing the All channels selection", async () => {
    vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    apiMock.menu.mockResolvedValue(response({ hungerstation: product("hungerstation", 25) }, 201));
    open("kudu", "?channel=all&q=Chicken");
    await screen.findByRole("table");
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(apiMock.menu).toHaveBeenLastCalledWith("kudu", "?q=Chicken&page=2"));
    expect((screen.getByRole("combobox") as HTMLSelectElement).value).toBe("all");
  });
});
