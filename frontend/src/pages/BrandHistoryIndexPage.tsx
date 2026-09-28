import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { BrandTabs } from "../components/BrandTabs";
import { DataTable } from "../components/DataTable";
import { PageHeader } from "../components/PageHeader";
import { SearchField } from "../components/SearchField";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { productHref } from "../lib/links";
import { formatRiyadhDateTime } from "../lib/dateTime";
import { setSearchParam } from "../lib/params";

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
      <div className="filter-bar">
        <SearchField
          label="Filter products"
          placeholder="Filter products"
          defaultValue={q}
          onCommit={(value) => setSearchParam(setParams, params, "q", value)}
        />
      </div>
      {!data?.items.length ? (
        <EmptyState message="No products to show history for." />
      ) : (
        <DataTable caption={`${brandId} products with observation history`}>
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
                <td className="nowrap">{product.channel}</td>
                <td className="nowrap">{formatRiyadhDateTime(product.lastSeenAt)}</td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
    </>
  );
}
