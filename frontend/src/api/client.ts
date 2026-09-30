import type {
  Brand,
  BrandOverview,
  ChangeEvent,
  Channel,
  PriceMapping,
  PriceMappingList,
  PriceMappingWrite,
  ListResponse,
  MarketOverview,
  Product,
  ProductHistory,
  Promotion,
  PullResponse,
} from "./types";

const BASE = "/api/v1";

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, body: unknown, message: string) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, init);
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail =
      body && typeof body === "object" && "detail" in body
        ? JSON.stringify((body as { detail: unknown }).detail)
        : response.statusText;
    throw new ApiError(response.status, body, detail);
  }
  return body as T;
}

async function allProducts(brand: string, channel: Channel): Promise<Product[]> {
  const items: Product[] = [];
  let page = 1;
  while (true) {
    const query = new URLSearchParams({
      channel,
      page: String(page),
      page_size: "500",
    });
    const response = await request<ListResponse<Product>>(
      `/brands/${brand}/products?${query.toString()}`,
    );
    items.push(...response.items);
    if (items.length >= response.meta.total || response.items.length === 0) break;
    page += 1;
  }
  return items;
}

export const api = {
  marketOverview: () => request<MarketOverview>("/market/overview"),
  pullStatus: () => request<PullResponse>("/market/pull"),
  startPullAll: () => request<PullResponse>("/market/pull", { method: "POST" }),
  hungerstationPullStatus: () => request<PullResponse>("/market/hungerstation/pull"),
  startHungerstationPull: () => request<PullResponse>("/market/hungerstation/pull", { method: "POST" }),
  marketChanges: (params = "") => request<ListResponse<ChangeEvent>>(`/market/changes${params}`),
  marketPromotions: (params = "") => request<ListResponse<Promotion>>(`/market/promotions${params}`),
  brands: () => request<ListResponse<Brand>>("/brands"),
  brandOverview: (brand: string) => request<BrandOverview>(`/brands/${brand}/overview`),
  products: (brand: string, params = "") =>
    request<ListResponse<Product>>(`/brands/${brand}/products${params}`),
  product: (brand: string, id: string) =>
    request<Product>(`/brands/${brand}/products/${encodeURIComponent(id)}`),
  productHistory: (brand: string, id: string) =>
    request<ProductHistory>(`/brands/${brand}/products/${encodeURIComponent(id)}/history`),
  promotions: (brand: string, params = "") =>
    request<ListResponse<Promotion>>(`/brands/${brand}/promotions${params}`),
  promotion: (brand: string, id: string) =>
    request<Promotion>(`/brands/${brand}/promotions/${encodeURIComponent(id)}`),
  changes: (brand: string, params = "") =>
    request<ListResponse<ChangeEvent>>(`/brands/${brand}/changes${params}`),
  change: (id: string) => request<ChangeEvent>(`/changes/${encodeURIComponent(id)}`),
  allProducts,
  playgroundMappings: () => request<PriceMappingList>("/playground/mappings"),
  playgroundMapping: (id: string) =>
    request<PriceMapping>(`/playground/mappings/${encodeURIComponent(id)}`),
  createPlaygroundMapping: (payload: PriceMappingWrite) =>
    request<PriceMapping>("/playground/mappings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  updatePlaygroundMapping: (id: string, payload: PriceMappingWrite) =>
    request<PriceMapping>(`/playground/mappings/${encodeURIComponent(id)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deletePlaygroundMapping: (id: string) =>
    request<void>(`/playground/mappings/${encodeURIComponent(id)}`, { method: "DELETE" }),
};
