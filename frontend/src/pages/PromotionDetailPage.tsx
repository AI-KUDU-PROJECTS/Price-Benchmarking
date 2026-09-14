import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Badge } from "../components/Badge";
import { BrandTabs } from "../components/BrandTabs";
import { PageHeader } from "../components/PageHeader";
import { Price } from "../components/Price";
import { ProductImage } from "../components/ProductImage";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { productHref } from "../lib/links";

export function PromotionDetailPage() {
  const { brandId = "kfc", promotionId = "" } = useParams();
  const { data, error, loading } = useApi(
    () => api.promotion(brandId, promotionId),
    [brandId, promotionId],
  );

  if (loading) return <LoadingState />;
  if (error) return <ErrorState error={error} />;
  if (!data) return <EmptyState message="Promotion not found." />;

  return (
    <>
      <PageHeader title={data.title || "Promotion"} subtitle={`${data.channel} · ${data.source || ""}`} />
      <BrandTabs brandId={brandId} />
      <div className="card" style={{ maxWidth: 520 }}>
        <ProductImage src={data.imageUrl} alt={data.title || ""} large />
        <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
          <Badge value={data.status} />
          {data.isNew ? <Badge value="new" /> : null}
        </div>
        <p>
          <Price value={data.promotionalPrice} currency="SAR" previous={data.regularPrice} />
        </p>
        <p>Discount: {data.discountPercent === null ? "—" : `${data.discountPercent}%`}</p>
        <p>First seen: {data.firstSeenAt || "—"}</p>
        <p>Last seen: {data.lastSeenAt || "—"}</p>
        {data.productId ? (
          <p>
            Linked product:{" "}
            <Link className="linkish" to={productHref(brandId, data.productId)}>Open history</Link>
          </p>
        ) : (
          <p className="subnav-note">No linked product identity in source.</p>
        )}
      </div>
    </>
  );
}
