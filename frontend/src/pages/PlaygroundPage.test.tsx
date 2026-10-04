import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type {
  Brand,
  MappingCompetitor,
  MappingProduct,
  PriceMapping,
  Product,
} from "../api/types";

const apiMock = vi.hoisted(() => ({
  brands: vi.fn(),
  playgroundMappings: vi.fn(),
  playgroundMapping: vi.fn(),
  allProducts: vi.fn(),
  product: vi.fn(),
  createPlaygroundMapping: vi.fn(),
  updatePlaygroundMapping: vi.fn(),
  deletePlaygroundMapping: vi.fn(),
}));

vi.mock("../api/client", () => ({
  api: apiMock,
  ApiError: class ApiError extends Error {
    status = 400;
    body: unknown = null;
  },
}));

import { PlaygroundPage } from "./PlaygroundPage";

const brands: Brand[] = [
  {
    id: "kudu",
    name: "KUDU",
    health: "healthy",
    lastSuccessfulRunAt: null,
    dataFreshness: "fresh",
    capabilities: { hasDiscount: false, hasSizePrices: false, hasImages: true },
    channels: ["pickup", "delivery", "hungerstation"],
    locationLabel: null,
  },
  {
    id: "kfc",
    name: "KFC",
    health: "healthy",
    lastSuccessfulRunAt: null,
    dataFreshness: "fresh",
    capabilities: { hasDiscount: true, hasSizePrices: true, hasImages: true },
    channels: ["pickup", "delivery", "hungerstation"],
    locationLabel: null,
  },
];

function makeProduct(
  id: string,
  brandId: string,
  regularPrice: number,
  specialPrice: number | null = null,
): Product {
  return {
    id,
    brandId,
    sourceId: id,
    nameAr: brandId === "kudu" ? "وجبة دجاج" : "عرض دجاج",
    nameEn: brandId === "kudu" ? "Chicken Meal" : "Chicken Offer",
    category: "Meals",
    categoryAr: null,
    imageUrl: `/images/${brandId}/${id}.jpg`,
    channel: "pickup",
    location: null,
    regularPrice,
    specialPrice,
    previousRegularPrice: null,
    previousSpecialPrice: null,
    currency: "SAR",
    sizes: [],
    availability: true,
    isPublished: true,
    isHidden: false,
    descriptionAr: null,
    descriptionEn: null,
    calories: null,
    status: "active",
    firstSeenAt: null,
    lastSeenAt: null,
    observedAt: null,
    sourceRunId: null,
  };
}

const kuduProduct = makeProduct("kudu-1", "kudu", 25);
const kfcProduct = makeProduct("kfc-1", "kfc", 30, 20);

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
  effectivePrice: 20,
  currency: "SAR",
  missing: false,
  differenceAmount: -5,
  differencePercentage: -20,
  pricePosition: "lower",
};

function savedMapping(name = "Saved benchmark"): PriceMapping {
  return {
    id: "mapping-1",
    name,
    channel: "pickup",
    kuduItem,
    competitorItems: [competitorItem],
    createdAt: "2026-09-30T08:00:00Z",
    updatedAt: "2026-09-30T08:00:00Z",
  };
}

function setupApi(mappings: PriceMapping[] = []) {
  apiMock.brands.mockResolvedValue({ items: brands });
  apiMock.playgroundMappings.mockResolvedValue({ items: mappings });
  apiMock.playgroundMapping.mockImplementation(async (id: string) => {
    const mapping = mappings.find((item) => item.id === id);
    if (!mapping) throw new Error("Mapping not found");
    return mapping;
  });
  apiMock.allProducts.mockImplementation(async (brandId: string) =>
    brandId === "kudu" ? [kuduProduct] : [kfcProduct],
  );
  apiMock.product.mockImplementation(async (brandId: string) =>
    brandId === "kudu" ? kuduProduct : kfcProduct,
  );
  apiMock.createPlaygroundMapping.mockResolvedValue(savedMapping("KUDU Chicken Meal · Pickup"));
  apiMock.updatePlaygroundMapping.mockImplementation(
    async (_id: string, payload: { name: string }) => savedMapping(payload.name),
  );
  apiMock.deletePlaygroundMapping.mockResolvedValue(undefined);
}

function renderPlayground(route = "/playground") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Routes>
        <Route path="/playground" element={<PlaygroundPage />} />
        <Route path="/playground/mappings/:mappingId" element={<h1>Mapping view destination</h1>} />
      </Routes>
    </MemoryRouter>,
  );
}

async function buildBasicComparison(user: ReturnType<typeof userEvent.setup>) {
  await user.selectOptions(screen.getByLabelText(/Choose channel/), "pickup");
  await waitFor(() => expect(apiMock.allProducts).toHaveBeenCalledWith("kudu", "pickup"));

  await user.click(await screen.findByRole("button", { name: "Choose KUDU item" }));
  const kuduDialog = screen.getByRole("dialog", { name: "Choose KUDU item" });
  await user.click(within(kuduDialog).getByRole("radio", { name: "Select Chicken Meal" }));
  await user.click(within(kuduDialog).getByRole("button", { name: "Use selected item" }));

  await user.click(await screen.findByRole("button", { name: "Add competitor items" }));
  const competitorDialog = screen.getByRole("dialog", { name: "Choose competitor items" });
  await user.click(within(competitorDialog).getByRole("checkbox", { name: "Select Chicken Offer" }));
  await user.click(within(competitorDialog).getByRole("button", { name: "Add 1 selected" }));
}

describe("PlaygroundPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupApi();
  });

  it("builds the four-step comparison with images and opens the saved flow", async () => {
    const user = userEvent.setup();
    renderPlayground();

    await screen.findByRole("heading", { name: "Playground" });
    expect(screen.queryByLabelText("Mapping flow canvas")).toBeNull();
    expect(screen.getByRole("heading", { name: "Choose KUDU item" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Choose competitor items" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: /Name and save mapping/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Choose KUDU item" }).hasAttribute("disabled")).toBe(true);
    expect(screen.getByRole("button", { name: "Add competitor items" }).hasAttribute("disabled")).toBe(true);
    expect((screen.getByLabelText(/Mapping name/) as HTMLInputElement).disabled).toBe(true);

    await buildBasicComparison(user);

    const comparisonTable = screen.getByRole("table", { name: "Current price comparison" });
    expect(screen.getByRole("img", { name: "Chicken Meal" })).toBeTruthy();
    expect(within(comparisonTable).getByRole("img", { name: "Chicken Offer" })).toBeTruthy();
    expect(within(comparisonTable).getByText("SAR -5.00")).toBeTruthy();
    expect(within(comparisonTable).getByText("-20.00%")).toBeTruthy();
    expect(within(comparisonTable).getByText("Lower")).toBeTruthy();
    expect(apiMock.product).not.toHaveBeenCalled();

    const nameInput = screen.getByLabelText(/Mapping name/) as HTMLInputElement;
    expect(nameInput.value).toBe("KUDU Chicken Meal · Pickup");

    await user.click(screen.getByRole("button", { name: "Save mapping" }));
    await waitFor(() => {
      expect(apiMock.createPlaygroundMapping).toHaveBeenCalledWith({
        name: "KUDU Chicken Meal · Pickup",
        channel: "pickup",
        kuduProductId: "kudu-1",
        competitorItems: [{ brandId: "kfc", productId: "kfc-1" }],
      });
    });
    expect(await screen.findByRole("heading", { name: "Mapping view destination" })).toBeTruthy();
  });

  it("loads a mapping from the edit URL and navigates back to its view after updating", async () => {
    setupApi([savedMapping()]);
    const user = userEvent.setup();
    renderPlayground("/playground?edit=mapping-1");

    const nameInput = await screen.findByLabelText(/Mapping name/) as HTMLInputElement;
    await waitFor(() => expect(nameInput.value).toBe("Saved benchmark"));
    expect(screen.getByRole("table", { name: "Current price comparison" })).toBeTruthy();
    expect(screen.queryByLabelText("Mapping flow canvas")).toBeNull();

    await user.clear(nameInput);
    await user.type(nameInput, "Updated benchmark");
    await user.click(screen.getByRole("button", { name: "Update mapping" }));

    await waitFor(() => {
      expect(apiMock.updatePlaygroundMapping).toHaveBeenCalledWith(
        "mapping-1",
        expect.objectContaining({ name: "Updated benchmark" }),
      );
    });
    expect(await screen.findByRole("heading", { name: "Mapping view destination" })).toBeTruthy();
  });

  it("offers View as the primary saved action and deletes only after confirmation", async () => {
    setupApi([savedMapping()]);
    const user = userEvent.setup();
    renderPlayground();

    await screen.findByText("Saved benchmark");
    expect(screen.getByRole("link", { name: "View" }).getAttribute("href"))
      .toBe("/playground/mappings/mapping-1");

    await user.click(screen.getByRole("button", { name: "Delete" }));
    const confirm = screen.getByRole("dialog", { name: "Delete mapping?" });
    await user.click(within(confirm).getByRole("button", { name: "Delete mapping" }));

    await waitFor(() => expect(apiMock.deletePlaygroundMapping).toHaveBeenCalledWith("mapping-1"));
    expect(await screen.findByText("No mappings have been saved yet.")).toBeTruthy();
  });

  it("removes competitor rows and keeps an actionable API error without losing selections", async () => {
    const user = userEvent.setup();
    apiMock.createPlaygroundMapping.mockRejectedValue(new Error("Local mapping database is unavailable."));
    renderPlayground();

    await screen.findByRole("heading", { name: "Playground" });
    await buildBasicComparison(user);

    await user.click(screen.getByRole("button", { name: "Save mapping" }));
    expect(await screen.findByText("Local mapping database is unavailable.")).toBeTruthy();
    expect((screen.getByLabelText(/Mapping name/) as HTMLInputElement).value)
      .toBe("KUDU Chicken Meal · Pickup");

    await user.click(screen.getByRole("button", { name: "Remove Chicken Offer" }));
    expect(screen.queryByRole("table", { name: "Current price comparison" })).toBeNull();
    expect(screen.getByText("No competitor items selected.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Save mapping" }).hasAttribute("disabled")).toBe(true);
  });

  it("confirms before a channel change clears the current comparison", async () => {
    const user = userEvent.setup();
    renderPlayground();
    await screen.findByRole("heading", { name: "Playground" });
    await buildBasicComparison(user);

    await user.selectOptions(screen.getByLabelText(/Choose channel/), "delivery");
    const confirm = screen.getByRole("dialog", { name: "Change channel?" });
    expect((screen.getByLabelText(/Choose channel/) as HTMLSelectElement).value).toBe("pickup");
    await user.click(within(confirm).getByRole("button", { name: "Change channel" }));

    expect((screen.getByLabelText(/Choose channel/) as HTMLSelectElement).value).toBe("delivery");
    expect(screen.queryByRole("img", { name: "Chicken Meal" })).toBeNull();
    expect(screen.queryByRole("table", { name: "Current price comparison" })).toBeNull();
  });
});
