import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { BrandTabs } from "../components/BrandTabs";
import { DataTable } from "../components/DataTable";
import { PageHeader } from "../components/PageHeader";
import { Pager } from "../components/Pager";
import { SearchField } from "../components/SearchField";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { productHref } from "../lib/links";
import { formatRiyadhDateTime } from "../lib/dateTime";
import { setPageParam, setSearchParam } from "../lib/params";

export function BrandHistoryIndexPage({ brandId }: { brandId: string }) {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") || "";
  const query = new URLSearchParams();
  if (q) query.set("q", q);
  if (params.get("page")) query.set("page", params.get("page") as string);
  const suffix = query.toString() ? `?${query}` : "";
  const { data, error, loading } = useApi(() => api.products(brandId, suffix), [brandId, suffix], { keepPreviousData: true });

  if (loading && !data) return <LoadingState />;
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
      <div className="results" aria-busy={loading}>
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
        {data && <Pager meta={data.meta} onPage={(page) => setPageParam(setParams, params, page)} />}
      </div>
    </>
  );
}
