import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { BrandTabs } from "../components/BrandTabs";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { productHref } from "../lib/links";

export function BrandHistoryIndexPage({ brandId }: { brandId: string }) {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") || "";
  const suffix = q ? `?q=${encodeURIComponent(q)}` : "";
  const { data, error, loading } = useApi(() => api.products(brandId, suffix), [brandId, suffix]);

  if (loading) return <LoadingState />;
  if (error) return <ErrorState error={error} />;

  return (
    <>
      <PageHeader
        title="History"
        subtitle="Pick a product to open its observation history. The canonical view is the product page."
      />
      <BrandTabs brandId={brandId} />
      <div className="filters">
        <input
          placeholder="Filter products"
          defaultValue={q}
          onBlur={(e) => {
            const next = new URLSearchParams(params);
            if (e.target.value) next.set("q", e.target.value);
            else next.delete("q");
            setParams(next);
          }}
        />
      </div>
      {!data?.items.length ? (
        <EmptyState message="No products to show history for." />
      ) : (
        <div className="card table-wrap">
          <table>
            <thead>
              <tr>
                <th>Product</th>
                <th>Channel</th>
                <th>Last seen</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((product) => (
                <tr key={product.id}>
                  <td>
                    <Link className="linkish" to={productHref(brandId, product.id)}>
                      {product.nameEn || product.id}
                    </Link>
                  </td>
                  <td>{product.channel}</td>
                  <td>{product.lastSeenAt || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
