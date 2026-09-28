import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Badge } from "../components/Badge";
import { BrandTabs } from "../components/BrandTabs";
import { DataBanner } from "../components/DataBanner";
import { PageHeader } from "../components/PageHeader";
import { Price } from "../components/Price";
import { ProductImage } from "../components/ProductImage";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { promotionHref } from "../lib/links";
import { formatRiyadhDateTime } from "../lib/dateTime";
import { setSearchParam } from "../lib/params";

export function BrandPromotionsPage({ brandId }: { brandId: string }) {
  const [params, setParams] = useSearchParams();
  const channel = params.get("channel") || "";
  const status = params.get("status") || "";
  const query = new URLSearchParams();
  if (channel) query.set("channel", channel);
  if (status) query.set("status", status);
  const suffix = query.toString() ? `?${query}` : "";
  const { data, error, loading } = useApi(() => api.promotions(brandId, suffix), [brandId, suffix]);

  if (loading) return <LoadingState variant="cards" />;
  if (error) return <ErrorState error={error} />;
  if (!data) return <EmptyState message="No promotions." />;

  return (
    <>
      <PageHeader title="Promotions" subtitle="Observed offers. Discount shown only when the source provides it." />
      <BrandTabs brandId={brandId} />
      <DataBanner freshness={data.meta.freshness} />
      <div className="filter-bar">
        <label className="visually-hidden" htmlFor="filter-channel">Channel</label>
        <select id="filter-channel" className="control" value={channel} onChange={(e) => setSearchParam(setParams, params, "channel", e.target.value)}>
          <option value="">All channels</option>
          <option value="pickup">Pickup</option>
          <option value="delivery">Delivery</option>
          {brandId !== "kudu" && <option value="hungerstation">HungerStation</option>}
        </select>
        <label className="visually-hidden" htmlFor="filter-status">Status</label>
        <select id="filter-status" className="control" value={status} onChange={(e) => setSearchParam(setParams, params, "status", e.target.value)}>
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
          {data.items.map((promo) => (
            <Link key={promo.id} className="card promo-card" to={promotionHref(brandId, promo.id)}>
              <ProductImage src={promo.imageUrl} alt={promo.title || ""} large />
              <div className="body">
                <div className="promo-meta">
                  <Badge value={promo.isNew ? "new" : promo.status} />
                  <span className="meta-text">{promo.channel}</span>
                </div>
                <h3>{promo.title || "Untitled offer"}</h3>
                <div>
                  <Price
                    value={promo.promotionalPrice}
                    currency="SAR"
                    previous={promo.regularPrice}
                  />
                </div>
                <div className="meta-text">
                  Discount: {promo.discountPercent === null ? "—" : `${promo.discountPercent}%`}
                </div>
                <div className="meta-text">
                  First {formatRiyadhDateTime(promo.firstSeenAt)} · Last {formatRiyadhDateTime(promo.lastSeenAt)}
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
