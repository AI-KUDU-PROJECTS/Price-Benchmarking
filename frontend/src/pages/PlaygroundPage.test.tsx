import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
  allProducts: vi.fn(),
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
  apiMock.allProducts.mockImplementation(async (brandId: string) =>
    brandId === "kudu" ? [kuduProduct] : [kfcProduct],
  );
  apiMock.createPlaygroundMapping.mockResolvedValue(
    savedMapping("KUDU Chicken Meal · Pickup"),
  );
  apiMock.updatePlaygroundMapping.mockImplementation(
    async (_id: string, payload: { name: string }) => savedMapping(payload.name),
  );
  apiMock.deletePlaygroundMapping.mockResolvedValue(undefined);
}

describe("PlaygroundPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupApi();
  });

  it("guides selection, previews effective-price differences, and saves", async () => {
    const user = userEvent.setup();
    render(<PlaygroundPage />);

    await screen.findByRole("heading", { name: "Playground" });
    const addCompetitors = screen.getByRole("button", { name: "Add competitor items" });
    expect(addCompetitors.hasAttribute("disabled")).toBe(true);

    await user.selectOptions(screen.getByLabelText(/Choose channel/), "pickup");
    await waitFor(() => expect(apiMock.allProducts).toHaveBeenCalledWith("kudu", "pickup"));

    await user.click(screen.getByRole("button", { name: "Choose KUDU item" }));
    const kuduDialog = screen.getByRole("dialog", { name: "Choose KUDU item" });
    const kuduSearch = within(kuduDialog).getByLabelText("Search products");
    await waitFor(() => {
      expect(document.activeElement).toBe(kuduSearch);
    });
    await user.click(within(kuduDialog).getByRole("radio", { name: "Select Chicken Meal" }));
    await user.click(within(kuduDialog).getByRole("button", { name: "Use selected item" }));

    expect(screen.getByRole("img", { name: "Chicken Meal" })).toBeTruthy();

    const nameInput = screen.getByLabelText("Mapping name") as HTMLInputElement;
    expect(nameInput.value).toBe("KUDU Chicken Meal · Pickup");

    await user.click(screen.getByRole("button", { name: "Add competitor items" }));
    const competitorDialog = screen.getByRole("dialog", { name: "Choose competitor items" });
    await user.type(within(competitorDialog).getByLabelText("Search products"), "offer");
    await user.click(within(competitorDialog).getByRole("checkbox", { name: "Select Chicken Offer" }));
    await user.click(within(competitorDialog).getByRole("button", { name: "Add 1 selected" }));

    expect(screen.getByRole("img", { name: "Chicken Offer" })).toBeTruthy();

    expect(screen.getByText("SAR -5.00")).toBeTruthy();
    expect(screen.getByText("-20.00%")).toBeTruthy();
    expect(screen.getByText("Lower")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Save mapping" }));
    await waitFor(() => {
      expect(apiMock.createPlaygroundMapping).toHaveBeenCalledWith({
        name: "KUDU Chicken Meal · Pickup",
        channel: "pickup",
        kuduProductId: "kudu-1",
        competitorItems: [{ brandId: "kfc", productId: "kfc-1" }],
      });
    });
    expect(await screen.findByText("Mapping saved.")).toBeTruthy();
  });

  it("loads a saved mapping, updates it, and deletes it after confirmation", async () => {
    setupApi([savedMapping()]);
    const user = userEvent.setup();
    render(<PlaygroundPage />);

    await screen.findByText("Saved benchmark");
    await user.click(screen.getByRole("button", { name: "Edit" }));

    const nameInput = screen.getByLabelText("Mapping name") as HTMLInputElement;
    expect(nameInput.value).toBe("Saved benchmark");
    await user.clear(nameInput);
    await user.type(nameInput, "Updated benchmark");
    await user.click(screen.getByRole("button", { name: "Update mapping" }));

    await waitFor(() => {
      expect(apiMock.updatePlaygroundMapping).toHaveBeenCalledWith(
        "mapping-1",
        expect.objectContaining({ name: "Updated benchmark" }),
      );
    });
    expect(await screen.findByText("Mapping updated.")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Delete" }));
    const confirm = screen.getByRole("dialog", { name: "Delete mapping?" });
    await user.click(within(confirm).getByRole("button", { name: "Delete mapping" }));

    await waitFor(() => expect(apiMock.deletePlaygroundMapping).toHaveBeenCalledWith("mapping-1"));
    expect(await screen.findByText("No mappings have been saved yet.")).toBeTruthy();
  });

  it("keeps selections and shows an actionable API error when save fails", async () => {
    const user = userEvent.setup();
    apiMock.createPlaygroundMapping.mockRejectedValue(new Error("Local mapping database is unavailable."));
    render(<PlaygroundPage />);

    await screen.findByRole("heading", { name: "Playground" });
    await user.selectOptions(screen.getByLabelText(/Choose channel/), "pickup");
    await waitFor(() => expect(apiMock.allProducts).toHaveBeenCalled());

    await user.click(screen.getByRole("button", { name: "Choose KUDU item" }));
    let dialog = screen.getByRole("dialog", { name: "Choose KUDU item" });
    await user.click(within(dialog).getByRole("radio", { name: "Select Chicken Meal" }));
    await user.click(within(dialog).getByRole("button", { name: "Use selected item" }));

    await user.click(screen.getByRole("button", { name: "Add competitor items" }));
    dialog = screen.getByRole("dialog", { name: "Choose competitor items" });
    await user.click(within(dialog).getByRole("checkbox", { name: "Select Chicken Offer" }));
    await user.click(within(dialog).getByRole("button", { name: "Add 1 selected" }));

    await user.click(screen.getByRole("button", { name: "Save mapping" }));
    expect(await screen.findByText("Local mapping database is unavailable.")).toBeTruthy();
    expect((screen.getByLabelText("Mapping name") as HTMLInputElement).value)
      .toBe("KUDU Chicken Meal · Pickup");
  });
});

