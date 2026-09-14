import type {
  Brand,
  BrandOverview,
  ChangeEvent,
  ListResponse,
  MarketOverview,
  Product,
  ProductHistory,
  Promotion,
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

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE}${path}`);
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

export const api = {
  marketOverview: () => request<MarketOverview>("/market/overview"),
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
};
