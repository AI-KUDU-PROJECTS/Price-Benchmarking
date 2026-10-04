import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { MappingCompetitor, MappingProduct, PriceMapping, Product } from "../api/types";

const apiMock = vi.hoisted(() => ({
  playgroundMapping: vi.fn(),
  product: vi.fn(),
}));

const ApiErrorMock = vi.hoisted(() => class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, body: unknown, message: string) {
    super(message);
    this.status = status;
    this.body = body;
  }
});

vi.mock("../api/client", () => ({
  api: apiMock,
  ApiError: ApiErrorMock,
}));

import { MappingViewPage } from "./MappingViewPage";

function product(
  id: string,
  brandId: string,
  nameEn: string,
  regularPrice: number,
  specialPrice: number | null = null,
): Product {
  return {
    id,
    brandId,
    sourceId: id,
    nameAr: brandId === "kudu" ? "وجبة دجاج" : "عرض دجاج",
    nameEn,
    category: "Meals",
    categoryAr: "وجبات",
    imageUrl: `/images/${brandId}/${id}.jpg`,
    channel: "pickup",
    location: "Riyadh",
    regularPrice,
    specialPrice,
    previousRegularPrice: brandId === "kudu" ? null : 32,
    previousSpecialPrice: null,
    currency: "SAR",
    sizes: brandId === "kudu" ? [] : [{ label: "Large", price: 35, currency: "SAR" }],
    availability: true,
    isPublished: true,
    isHidden: false,
    descriptionAr: brandId === "kudu" ? "وجبة دجاج لذيذة" : null,
    descriptionEn: brandId === "kudu" ? "A freshly prepared chicken meal." : null,
    calories: brandId === "kudu" ? 640 : null,
    status: "active",
    firstSeenAt: "2026-09-01T08:00:00Z",
    lastSeenAt: "2026-09-30T08:00:00Z",
    observedAt: "2026-09-30T08:00:00Z",
    sourceRunId: null,
  };
}

const kuduProduct = product("kudu-1", "kudu", "Chicken Meal", 25);
const kfcProduct = product("kfc-1", "kfc", "Chicken Offer", 30, 28);

const kuduItem: MappingProduct = {
  brandId: "kudu",
  brandName: "KUDU",
  productId: "kudu-1",
  nameAr: "وجبة دجاج",
  nameEn: "Chicken Meal",
  category: "Meals",
  imageUrl: "/images/kudu/kudu-1.jpg",
  effectivePrice: 25,
  currency: "SAR",
  missing: false,
};

const competitorItem: MappingCompetitor = {
  brandId: "kfc",
  brandName: "KFC",
  productId: "kfc-1",
  nameAr: "عرض دجاج",
  nameEn: "Chicken Offer",
  category: "Meals",
  imageUrl: "/images/kfc/kfc-1.jpg",
  effectivePrice: 28,
  currency: "SAR",
  missing: false,
  differenceAmount: 3,
  differencePercentage: 12,
  pricePosition: "higher",
};

const missingItem: MappingCompetitor = {
  brandId: "hardees",
  brandName: "Hardee's",
  productId: "missing-1",
  nameAr: null,
  nameEn: "Legacy Burger",
  category: null,
  imageUrl: null,
  effectivePrice: null,
  currency: null,
  missing: true,
  differenceAmount: null,
  differencePercentage: null,
  pricePosition: "unavailable",
};

const mapping: PriceMapping = {
  id: "mapping-1",
  name: "Chicken meals · Pickup",
  channel: "pickup",
  kuduItem,
  competitorItems: [competitorItem, missingItem],
  createdAt: "2026-09-30T08:00:00Z",
  updatedAt: "2026-09-30T09:00:00Z",
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/playground/mappings/mapping-1"]}>
      <Routes>
        <Route path="/playground/mappings/:mappingId" element={<MappingViewPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("MappingViewPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.playgroundMapping.mockResolvedValue(mapping);
    apiMock.product.mockImplementation(async (brandId: string) =>
      brandId === "kudu" ? kuduProduct : kfcProduct,
    );
  });

  it("loads a direct mapping URL, summarizes live prices, and selects KUDU first", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "Chicken meals · Pickup" })).toBeTruthy();
    expect(screen.getByText(/KUDU is cheaper than 1 of 1 comparable item/)).toBeTruthy();
    expect(screen.getByText(/1 mapped item is unavailable/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Edit mapping" }).getAttribute("href"))
      .toBe("/playground?edit=mapping-1");
    expect((await screen.findByRole("button", { name: "Show details for Chicken Meal" })).getAttribute("aria-pressed"))
      .toBe("true");

    await waitFor(() => expect(apiMock.product).toHaveBeenCalledWith("kudu", "kudu-1"));
    expect(await screen.findByText("A freshly prepared chicken meal.")).toBeTruthy();
    expect(screen.getByText("640")).toBeTruthy();
  });

  it("shows full competitor details and reuses its cached product request", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { name: "Chicken meals · Pickup" });

    await user.click(await screen.findByRole("button", { name: "Show details for Chicken Offer" }));
    const details = document.getElementById("mapping-item-details") as HTMLElement;
    await within(details).findByText("Not provided by source.");
    expect(within(details).getByText("Large:")).toBeTruthy();
    expect(within(details).getAllByText(/SAR \+3.00/).length).toBeGreaterThan(0);
    expect(within(details).getByText(/12.00%/)).toBeTruthy();
    expect(within(details).getByText("Previous regular")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Show details for Chicken Meal" }));
    await within(details).findByText("A freshly prepared chicken meal.");
    await user.click(screen.getByRole("button", { name: "Show details for Chicken Offer" }));
    await within(details).findByText("Not provided by source.");

    const competitorCalls = apiMock.product.mock.calls.filter(
      ([brandId, productId]) => brandId === "kfc" && productId === "kfc-1",
    );
    expect(competitorCalls).toHaveLength(1);
  });

  it("keeps missing items in the flow without requesting stale details", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { name: "Chicken meals · Pickup" });

    await user.click(await screen.findByRole("button", { name: "Show details for Legacy Burger" }));
    const details = document.getElementById("mapping-item-details") as HTMLElement;
    expect(await within(details).findByText("No longer available")).toBeTruthy();
    expect(within(details).getByText(/no old price is used/i)).toBeTruthy();
    expect(apiMock.product).not.toHaveBeenCalledWith("hardees", "missing-1");
  });

  it("distinguishes a missing mapping from a general loading failure", async () => {
    apiMock.playgroundMapping.mockRejectedValueOnce(new ApiErrorMock(404, null, "Not found"));
    const { unmount } = renderPage();
    expect(await screen.findByText(/mapping could not be found/i)).toBeTruthy();
    unmount();

    apiMock.playgroundMapping.mockRejectedValueOnce(new Error("Mapping service unavailable"));
    renderPage();
    expect(await screen.findByText("Could not load this page")).toBeTruthy();
    expect(screen.getByText("Mapping service unavailable")).toBeTruthy();
  });
});
