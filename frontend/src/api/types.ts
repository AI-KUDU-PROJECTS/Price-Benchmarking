export type Health = "healthy" | "partial" | "stale" | "error" | "disconnected";
export type Freshness = "fresh" | "stale" | "unavailable";
export type Channel = "pickup" | "delivery";

export interface BrandCapabilities {
  hasDiscount: boolean;
  hasSizePrices: boolean;
  hasImages: boolean;
}

export interface Brand {
  id: string;
  name: string;
  health: Health;
  lastSuccessfulRunAt: string | null;
  dataFreshness: Freshness;
  capabilities: BrandCapabilities;
  channels: Channel[];
  locationLabel: string | null;
}

export interface ProductSize {
  label: string;
  price: number | null;
  currency: string | null;
}

export interface Product {
  id: string;
  brandId: string;
  sourceId: string;
  nameAr: string | null;
  nameEn: string | null;
  category: string | null;
  imageUrl: string | null;
  channel: Channel;
  location: string | null;
  regularPrice: number | null;
  specialPrice: number | null;
  previousRegularPrice: number | null;
  previousSpecialPrice: number | null;
  currency: string | null;
  sizes: ProductSize[];
  availability: boolean | null;
  status: "active" | "not_observed" | "removed" | "returned";
  firstSeenAt: string | null;
  lastSeenAt: string | null;
  observedAt: string | null;
  sourceRunId: string | null;
}

export interface Promotion {
  id: string;
  brandId: string;
  productId: string | null;
  title: string | null;
  imageUrl: string | null;
  status: "active" | "not_observed" | "ended" | "returned";
  isNew: boolean;
  regularPrice: number | null;
  promotionalPrice: number | null;
  discountPercent: number | null;
  firstSeenAt: string | null;
  lastSeenAt: string | null;
  channel: Channel;
  source: string | null;
  category: string | null;
}

export interface ChangeEvent {
  id: string;
  brandId: string;
  productId: string | null;
  promotionId: string | null;
  type: string;
  title: string | null;
  beforeValue: string | null;
  afterValue: string | null;
  percentageChange: number | null;
  detectedAt: string;
  channel: Channel;
  location: string | null;
  sourceRunId: string | null;
  category: string | null;
}

export interface CollectionRun {
  id: string;
  brandId: string;
  status: "running" | "success" | "partial" | "failed";
  startedAt: string | null;
  completedAt: string | null;
  channel: Channel;
  location: string | null;
  itemCount: number | null;
  warningCount: number | null;
  errorSummary: string | null;
}

export interface Observation {
  observedAt: string | null;
  sourceRunId: string | null;
  channel: Channel;
  regularPrice: number | null;
  specialPrice: number | null;
  availability: boolean | null;
  imageUrl: string | null;
  sizes: ProductSize[];
}

export interface ProductHistory {
  product: Product;
  observations: Observation[];
}

export interface Highlight {
  id: string;
  rank: number;
  type: string;
  title: string;
  summary: string | null;
  brandId: string;
  href: string;
  detectedAt: string;
  channel: Channel;
  changeId: string;
  productId: string | null;
  promotionId: string | null;
}

export interface ListMeta {
  page: number;
  pageSize: number;
  total: number;
  freshness: Freshness;
  sourceRunIds: string[];
  generatedAt: string;
  timezone: string;
}

export interface ListResponse<T> {
  items: T[];
  meta: ListMeta;
}

export interface BrandStatusRow {
  brand: Brand;
  productCount: number | null;
  promotionCount: number | null;
  changeCount: number | null;
}

export interface MarketOverview {
  lastUpdatedAt: string | null;
  freshness: Freshness;
  connectedBrandIds: string[];
  counts: {
    priceDecreases: number;
    priceIncreases: number;
    newProducts: number;
    newOffers: number;
    endedOffers: number;
  };
  highlights: Highlight[];
  brands: BrandStatusRow[];
}

export interface BrandOverview {
  brand: Brand;
  runs: CollectionRun[];
  productCount: number;
  promotionCount: number;
  recentChanges: ChangeEvent[];
  highlights: Highlight[];
}
