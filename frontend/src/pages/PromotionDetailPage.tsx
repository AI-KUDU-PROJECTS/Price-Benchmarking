import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { BackLink } from "../components/BackLink";
import { Badge } from "../components/Badge";
import { BrandTabs } from "../components/BrandTabs";
import { PageHeader } from "../components/PageHeader";
import { Price } from "../components/Price";
import { ProductImage } from "../components/ProductImage";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { productHref } from "../lib/links";
import { formatRiyadhDateTime } from "../lib/dateTime";

export function PromotionDetailPage({ brandId }: { brandId: string }) {
  const { promotionId = "" } = useParams();
  const { data, error, loading } = useApi(
    () => api.promotion(brandId, promotionId),
    [brandId, promotionId],
  );

  if (loading) return <LoadingState variant="detail" />;
  if (error) return <ErrorState error={error} />;
  if (!data) return <EmptyState message="Promotion not found." />;

  return (
    <>
      <div className="page-header-back">
        <BackLink label="Back to promotions" fallback={`/competitors/${brandId}/promotions`} />
      </div>
      <PageHeader title={data.title || "Promotion"} subtitle={`${data.channel} · ${data.source || ""}`} />
      <BrandTabs brandId={brandId} />
      <div className="card detail-card">
        <ProductImage src={data.imageUrl} alt={data.title || ""} large />
        <div className="promo-meta" style={{ marginTop: 12 }}>
          <Badge value={data.status} />
          {data.isNew ? <Badge value="new" /> : null}
        </div>
        <p style={{ marginTop: 12 }}>
          <Price value={data.promotionalPrice} currency="SAR" previous={data.regularPrice} />
        </p>
        <div className="stack">
          <div className="field-row"><span className="field-label">Discount</span><span className="field-value">{data.discountPercent === null ? "—" : `${data.discountPercent}%`}</span></div>
          <div className="field-row"><span className="field-label">First seen</span><span className="field-value">{formatRiyadhDateTime(data.firstSeenAt)}</span></div>
          <div className="field-row"><span className="field-label">Last seen</span><span className="field-value">{formatRiyadhDateTime(data.lastSeenAt)}</span></div>
        </div>
        {data.productId ? (
          <div className="action-row">
            <Link className="btn btn-secondary btn-sm" to={productHref(brandId, data.productId)}>
              Open linked product history
            </Link>
          </div>
        ) : (
          <p className="meta-text" style={{ marginTop: 16 }}>No linked product identity in source.</p>
        )}
      </div>
    </>
  );
}
