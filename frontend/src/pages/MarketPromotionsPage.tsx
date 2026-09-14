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
  for (const key of ["brand", "channel", "status"] as const) {
    const value = params.get(key);
    if (value) query.set(key, value);
  }
  const suffix = query.toString() ? `?${query}` : "";
  const { data, error, loading } = useApi(() => api.marketPromotions(suffix), [suffix]);

  if (loading) return <LoadingState />;
  if (error) return <ErrorState error={error} />;
  if (!data) return <EmptyState message="No market promotions." />;

  return (
    <>
      <PageHeader title="Promotions" subtitle="Observed offers across connected competitors." />
      <DataBanner freshness={data.meta.freshness} />
      <div className="filters">
        <select value={params.get("brand") || ""} onChange={(event) => write(setParams, params, "brand", event.target.value)}>
          {BRANDS.map(([value, label]) => <option key={value || "all"} value={value}>{label}</option>)}
        </select>
        <select value={params.get("channel") || ""} onChange={(event) => write(setParams, params, "channel", event.target.value)}>
          <option value="">All channels</option>
          <option value="pickup">Pickup</option>
          <option value="delivery">Delivery</option>
        </select>
        <select value={params.get("status") || ""} onChange={(event) => write(setParams, params, "status", event.target.value)}>
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="new">New</option>
          <option value="ended">Ended</option>
          <option value="not_observed">Not observed</option>
          <option value="returned">Returned</option>
        </select>
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
                <div className="subnav-note">Discount: {promotion.discountPercent === null ? "—" : `${promotion.discountPercent}%`}</div>
                <div className="subnav-note">First {promotion.firstSeenAt || "—"} · Last {promotion.lastSeenAt || "—"}</div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}

function write(setParams: (params: URLSearchParams) => void, params: URLSearchParams, key: string, value: string) {
  const next = new URLSearchParams(params);
  if (value) next.set(key, value);
  else next.delete(key);
  setParams(next);
}

function labelForBrand(id: string) {
  return BRANDS.find(([value]) => value === id)?.[1] || id;
}
