import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Badge } from "../components/Badge";
import { DataBanner } from "../components/DataBanner";
import { PageHeader } from "../components/PageHeader";
import { Price } from "../components/Price";
import { ProductImage } from "../components/ProductImage";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { promotionHref } from "../lib/links";
import { formatRiyadhDateTime } from "../lib/dateTime";
import { clearSearchParams, setSearchParam } from "../lib/params";

const FILTER_KEYS = ["brand", "channel", "status"] as const;

const BRANDS = [
  ["", "All brands"],
  ["kfc", "KFC"],
  ["hardees", "Hardee's"],
  ["burger-king", "Burger King"],
  ["herfy", "Herfy"],
];

export function MarketPromotionsPage() {
  const [params, setParams] = useSearchParams();
  const query = new URLSearchParams();
  for (const key of FILTER_KEYS) {
    const value = params.get(key);
    if (value) query.set(key, value);
  }
  const suffix = query.toString() ? `?${query}` : "";
  const { data, error, loading } = useApi(() => api.marketPromotions(suffix), [suffix]);
  const hasFilters = FILTER_KEYS.some((key) => params.get(key));

  if (loading) return <LoadingState variant="cards" />;
  if (error) return <ErrorState error={error} />;
  if (!data) return <EmptyState message="No market promotions." />;

  return (
    <>
      <PageHeader title="Promotions" subtitle="Observed offers across connected competitors." />
      <DataBanner freshness={data.meta.freshness} />
      <div className="filter-bar">
        <label className="visually-hidden" htmlFor="filter-brand">Brand</label>
        <select id="filter-brand" className="control" value={params.get("brand") || ""} onChange={(event) => setSearchParam(setParams, params, "brand", event.target.value)}>
          {BRANDS.map(([value, label]) => <option key={value || "all"} value={value}>{label}</option>)}
        </select>
        <label className="visually-hidden" htmlFor="filter-channel">Channel</label>
        <select id="filter-channel" className="control" value={params.get("channel") || ""} onChange={(event) => setSearchParam(setParams, params, "channel", event.target.value)}>
          <option value="">All channels</option>
          <option value="pickup">Pickup</option>
          <option value="delivery">Delivery</option>
        </select>
        <label className="visually-hidden" htmlFor="filter-status">Status</label>
        <select id="filter-status" className="control" value={params.get("status") || ""} onChange={(event) => setSearchParam(setParams, params, "status", event.target.value)}>
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="new">New</option>
          <option value="ended">Ended</option>
          <option value="not_observed">Not observed</option>
          <option value="returned">Returned</option>
        </select>
        {hasFilters ? (
          <button type="button" className="clear-filters" onClick={() => clearSearchParams(setParams, params, FILTER_KEYS)}>
            Clear filters
          </button>
        ) : null}
      </div>
      {data.items.length === 0 ? (
        <EmptyState message="No promotions match these filters." />
      ) : (
        <div className="grid cards">
          {data.items.map((promotion) => (
            <Link key={`${promotion.brandId}-${promotion.id}`} className="card promo-card" to={promotionHref(promotion.brandId, promotion.id)}>
              <ProductImage src={promotion.imageUrl} alt={promotion.title || ""} large />
              <div className="body">
                <div className="promo-meta"><Badge value={promotion.isNew ? "new" : promotion.status} /><span className="meta-text">{labelForBrand(promotion.brandId)} · {promotion.channel}</span></div>
                <h3>{promotion.title || "Untitled offer"}</h3>
                <Price value={promotion.promotionalPrice} currency="SAR" previous={promotion.regularPrice} />
                <div className="meta-text">Discount: {promotion.discountPercent === null ? "—" : `${promotion.discountPercent}%`}</div>
                <div className="meta-text">First {formatRiyadhDateTime(promotion.firstSeenAt)} · Last {formatRiyadhDateTime(promotion.lastSeenAt)}</div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}

function labelForBrand(id: string) {
  return BRANDS.find(([value]) => value === id)?.[1] || id;
}
