import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Badge } from "../components/Badge";
import { BrandTabs } from "../components/BrandTabs";
import { PageHeader } from "../components/PageHeader";
import { Price } from "../components/Price";
import { ProductImage } from "../components/ProductImage";
import { SizeList } from "../components/SizeList";
import { EmptyState, ErrorState, LoadingState } from "../components/States";

export function ProductHistoryPage() {
  const { brandId = "kfc", productId = "" } = useParams();
  const { data, error, loading } = useApi(
    () => api.productHistory(brandId, productId),
    [brandId, productId],
  );

  if (loading) return <LoadingState />;
  if (error) return <ErrorState error={error} />;
  if (!data) return <EmptyState message="Product not found." />;
  const product = data.product;

  return (
    <>
      <PageHeader
        title={product.nameEn || product.nameAr || "Product history"}
        subtitle={`${product.channel} · ${product.location || "Riyadh branch"}`}
      />
      <BrandTabs brandId={brandId} />
      <div className="grid two">
        <div className="card">
          <ProductImage src={product.imageUrl} alt={product.nameEn || ""} large />
          <div style={{ marginTop: 12 }}>
            <Badge value={product.status} /> <span className="meta-text">{product.channel}</span>
          </div>
          <p>{product.nameAr || "Arabic name unavailable from source."}</p>
          <p>Category: {product.category || "—"}</p>
          <p>
            Current: <Price value={product.specialPrice ?? product.regularPrice} currency={product.currency} />
          </p>
          <p>
            Previous:{" "}
            <Price
              value={product.previousSpecialPrice ?? product.previousRegularPrice}
              currency={product.currency}
            />
          </p>
          <SizeList sizes={product.sizes} currency={product.currency} />
        </div>
        <div className="card">
          <h2>Observations over time</h2>
          {data.observations.length === 0 ? (
            <EmptyState message="No successful-run observations for this product." />
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Observed</th>
                  <th>Regular</th>
                  <th>Special</th>
                  <th>Available</th>
                </tr>
              </thead>
              <tbody>
                {data.observations.map((row) => (
                  <tr key={`${row.sourceRunId}-${row.observedAt}`}>
                    <td>{row.observedAt || "—"}</td>
                    <td><Price value={row.regularPrice} currency={product.currency} /></td>
                    <td><Price value={row.specialPrice} currency={product.currency} /></td>
                    <td>{row.availability === null ? "—" : row.availability ? "Yes" : "No"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="subnav-note">
            <Link className="linkish" to={`/competitors/${brandId}/menu`}>Back to menu</Link>
          </p>
        </div>
      </div>
    </>
  );
}
