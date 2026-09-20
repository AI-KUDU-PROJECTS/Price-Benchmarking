import { useParams } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { BackLink } from "../components/BackLink";
import { Badge } from "../components/Badge";
import { BrandTabs } from "../components/BrandTabs";
import { DataTable } from "../components/DataTable";
import { PageHeader } from "../components/PageHeader";
import { Price } from "../components/Price";
import { ProductImage } from "../components/ProductImage";
import { SizeList } from "../components/SizeList";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { formatRiyadhDateTime } from "../lib/dateTime";

export function ProductHistoryPage({ brandId }: { brandId: string }) {
  const { productId = "" } = useParams();
  const { data, error, loading } = useApi(
    () => api.productHistory(brandId, productId),
    [brandId, productId],
  );

  if (loading) return <LoadingState variant="detail" />;
  if (error) return <ErrorState error={error} />;
  if (!data) return <EmptyState message="Product not found." />;
  const product = data.product;

  return (
    <>
      <div className="page-header-back">
        <BackLink label="Back to menu" fallback={`/competitors/${brandId}/menu`} />
      </div>
      <PageHeader
        title={product.nameEn || product.nameAr || "Product history"}
        subtitle={`${product.channel} · ${product.location || "Riyadh branch"}`}
      />
      <BrandTabs brandId={brandId} />
      <div className="detail-grid">
        <div className="card">
          <ProductImage src={product.imageUrl} alt={product.nameEn || ""} large />
          <div className="promo-meta" style={{ marginTop: 12 }}>
            <Badge value={product.status} /> <span className="meta-text">{product.channel}</span>
          </div>
          <p className="meta-text" style={{ marginTop: 8 }}>{product.nameAr || "Arabic name unavailable from source."}</p>
          <div className="stack" style={{ marginTop: 12 }}>
            <div className="field-row"><span className="field-label">Category</span><span className="field-value">{product.category || "—"}</span></div>
            <div className="field-row">
              <span className="field-label">Current</span>
              <Price value={product.specialPrice ?? product.regularPrice} currency={product.currency} />
            </div>
            <div className="field-row">
              <span className="field-label">Previous</span>
              <Price
                value={product.previousSpecialPrice ?? product.previousRegularPrice}
                currency={product.currency}
              />
            </div>
          </div>
          <div className="field-row" style={{ marginTop: 12 }}>
            <span className="field-label">Sizes</span>
            <SizeList sizes={product.sizes} currency={product.currency} />
          </div>
        </div>
        <div className="card">
          <h2 className="panel-title">Observations over time</h2>
          {data.observations.length === 0 ? (
            <EmptyState message="No successful-run observations for this product." />
          ) : (
            <DataTable caption="Product price and availability observations over time">
              <thead>
                <tr>
                  <th>Observed</th>
                  <th className="num">Regular</th>
                  <th className="num">Special</th>
                  <th>Available</th>
                </tr>
              </thead>
              <tbody>
                {data.observations.map((row) => (
                  <tr key={`${row.sourceRunId}-${row.observedAt}`}>
                    <td className="nowrap">{formatRiyadhDateTime(row.observedAt)}</td>
                    <td className="num"><Price value={row.regularPrice} currency={product.currency} /></td>
                    <td className="num"><Price value={row.specialPrice} currency={product.currency} /></td>
                    <td>{row.availability === null ? "—" : row.availability ? "Yes" : "No"}</td>
                  </tr>
                ))}
              </tbody>
            </DataTable>
          )}
        </div>
      </div>
    </>
  );
}
