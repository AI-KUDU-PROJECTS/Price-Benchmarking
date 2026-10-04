import { beforeEach, describe, expect, it } from "vitest";
import type { Brand, PriceMappingWrite, Product } from "./types";
import {
  createPlaygroundDemoApi,
  PLAYGROUND_DEMO_STORAGE_KEY,
} from "./playgroundDemoStorage";

const brands: Brand[] = [
  {
    id: "kudu",
    name: "KUDU",
    health: "healthy",
    lastSuccessfulRunAt: null,
    dataFreshness: "fresh",
    capabilities: { hasDiscount: false, hasSizePrices: false, hasImages: true },
    channels: ["pickup"],
    locationLabel: null,
  },
  {
    id: "kfc",
    name: "KFC",
    health: "healthy",
    lastSuccessfulRunAt: null,
    dataFreshness: "fresh",
    capabilities: { hasDiscount: true, hasSizePrices: false, hasImages: true },
    channels: ["pickup"],
    locationLabel: null,
  },
];

function product(
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

const payload: PriceMappingWrite = {
  name: "Chicken benchmark",
  channel: "pickup",
  kuduProductId: "kudu-1",
  competitorItems: [{ brandId: "kfc", productId: "kfc-1" }],
};

describe("playground browser demo storage", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("persists references in the browser and refreshes live prices when reopened", async () => {
    const products = new Map<string, Product>([
      ["kudu::kudu-1", product("kudu-1", "kudu", 25)],
      ["kfc::kfc-1", product("kfc-1", "kfc", 30, 20)],
    ]);
    const dependencies = {
      storage: window.localStorage,
      loadBrands: async () => brands,
      loadProduct: async (brandId: string, productId: string) =>
        products.get(`${brandId}::${productId}`) || null,
      now: () => new Date("2026-10-01T08:00:00Z"),
      randomId: () => "mapping-1",
    };
    const api = createPlaygroundDemoApi(dependencies);

    const created = await api.create(payload);
    expect(created.id).toBe("mapping-1");
    expect(created.competitorItems[0].effectivePrice).toBe(20);
    expect(created.competitorItems[0].differenceAmount).toBe(-5);

    const storedJson = window.localStorage.getItem(PLAYGROUND_DEMO_STORAGE_KEY) || "";
    expect(storedJson).toContain("kfc-1");
    expect(storedJson).not.toContain("regularPrice");
    expect(storedJson).not.toContain("effectivePrice");

    products.set("kfc::kfc-1", product("kfc-1", "kfc", 35));
    const reopenedApi = createPlaygroundDemoApi(dependencies);
    const reopened = await reopenedApi.get("mapping-1");
    expect(reopened?.competitorItems[0].effectivePrice).toBe(35);
    expect(reopened?.competitorItems[0].differenceAmount).toBe(10);
  });

  it("keeps a missing item by fallback name and supports update and delete", async () => {
    const products = new Map<string, Product>([
      ["kudu::kudu-1", product("kudu-1", "kudu", 25)],
      ["kfc::kfc-1", product("kfc-1", "kfc", 30)],
    ]);
    let timestamp = "2026-10-01T08:00:00Z";
    const api = createPlaygroundDemoApi({
      storage: window.localStorage,
      loadBrands: async () => brands,
      loadProduct: async (brandId, productId) =>
        products.get(`${brandId}::${productId}`) || null,
      now: () => new Date(timestamp),
      randomId: () => "mapping-1",
    });

    await api.create(payload);
    timestamp = "2026-10-01T09:00:00Z";
    const updated = await api.update("mapping-1", { ...payload, name: "Updated demo" });
    expect(updated?.name).toBe("Updated demo");
    expect(updated?.createdAt).toBe("2026-10-01T08:00:00.000Z");
    expect(updated?.updatedAt).toBe("2026-10-01T09:00:00.000Z");

    products.delete("kfc::kfc-1");
    const missing = await api.get("mapping-1");
    expect(missing?.competitorItems[0].missing).toBe(true);
    expect(missing?.competitorItems[0].nameEn).toBe("Chicken Offer");
    expect(missing?.competitorItems[0].effectivePrice).toBeNull();

    expect(await api.delete("mapping-1")).toBe(true);
    expect(await api.get("mapping-1")).toBeNull();
  });

  it("rejects duplicate competitor selections before writing", async () => {
    const products = new Map<string, Product>([
      ["kudu::kudu-1", product("kudu-1", "kudu", 25)],
      ["kfc::kfc-1", product("kfc-1", "kfc", 30)],
    ]);
    const api = createPlaygroundDemoApi({
      storage: window.localStorage,
      loadBrands: async () => brands,
      loadProduct: async (brandId, productId) =>
        products.get(`${brandId}::${productId}`) || null,
      randomId: () => "mapping-1",
    });

    await expect(api.create({
      ...payload,
      competitorItems: [payload.competitorItems[0], payload.competitorItems[0]],
    })).rejects.toThrow("same competitor item");
    expect(window.localStorage.getItem(PLAYGROUND_DEMO_STORAGE_KEY)).toBeNull();
  });
});
