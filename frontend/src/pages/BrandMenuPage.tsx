import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Badge } from "../components/Badge";
import { BrandTabs } from "../components/BrandTabs";
import { DataBanner } from "../components/DataBanner";
import { DataTable } from "../components/DataTable";
import { PageHeader } from "../components/PageHeader";
import { Price } from "../components/Price";
import { ProductImage } from "../components/ProductImage";
import { SearchField } from "../components/SearchField";
import { SizeList } from "../components/SizeList";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { productHref } from "../lib/links";
import { formatRiyadhDateTime } from "../lib/dateTime";
import { setSearchParam } from "../lib/params";

export function BrandMenuPage({ brandId }: { brandId: string }) {
  const [params, setParams] = useSearchParams();
  const isKudu = brandId === "kudu";
  const channel = params.get("channel") || (isKudu ? "delivery" : "");
  const q = params.get("q") || "";
  const query = new URLSearchParams();
  if (channel) query.set("channel", channel);
  if (q) query.set("q", q);
  const suffix = query.toString() ? `?${query}` : "";
  const { data, error, loading } = useApi(() => api.products(brandId, suffix), [brandId, suffix]);

  if (loading) return <LoadingState />;
  if (error) return <ErrorState error={error} />;
  if (!data) return <EmptyState message="No products." />;

  return (
    <>
      <PageHeader
        title={isKudu ? "KUDU menu" : "Menu"}
        subtitle={isKudu
          ? "Production menu · template 1 · prices and images from the latest saved collection"
          : "Latest successful collection. Missing prices stay blank."}
      />
      <BrandTabs brandId={brandId} />
      <DataBanner freshness={data.meta.freshness} lastUpdatedAt={isKudu ? data.items[0]?.observedAt : undefined} />
      <div className="filter-bar">
        <SearchField
          label="Search products"
          placeholder="Search name or category"
          defaultValue={q}
          onCommit={(value) => setSearchParam(setParams, params, "q", value)}
        />
        <label className="visually-hidden" htmlFor="filter-channel">Channel</label>
        <select
          id="filter-channel"
          className="control"
          value={channel}
          onChange={(e) => setSearchParam(setParams, params, "channel", e.target.value)}
        >
          {!isKudu && <option value="">All channels</option>}
          <option value="pickup">Pickup</option>
          <option value="delivery">Delivery</option>
          {!isKudu && <option value="hungerstation">HungerStation</option>}
        </select>
      </div>
      {data.items.length === 0 ? (
        <EmptyState message="No products match these filters." />
      ) : (
        <DataTable caption={`${brandId} menu items`}>
          <thead>
            <tr>
              <th><span className="visually-hidden">Image</span></th>
              <th>Product</th>
              <th>Category</th>
              <th>Channel</th>
              <th className="num">{isKudu ? "Price" : "Current"}</th>
              {!isKudu && <th className="num">Previous</th>}
              {!isKudu && <th>Sizes</th>}
              <th>{isKudu ? "Collected" : "Last seen"}</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((product) => (
              <tr key={product.id}>
                <td><ProductImage src={product.imageUrl} alt={product.nameEn || ""} /></td>
                <td>
                  <Link className="linkish" to={productHref(brandId, product.id)}>
                    {product.nameEn || product.nameAr || product.id}
                  </Link>
                  <div className="meta-text">{product.nameAr || "Arabic name unavailable"}</div>
                  <Badge value={product.isPublished === false ? "unpublished" : product.status} />
                </td>
                <td>{product.category || "—"}{isKudu && product.categoryAr && <div className="meta-text">{product.categoryAr}</div>}</td>
                <td className="nowrap">{product.channel}</td>
                <td className="num">
                  <Price
                    value={product.specialPrice ?? product.regularPrice}
                    currency={product.currency}
                    previous={product.previousSpecialPrice ?? product.previousRegularPrice}
                    showPreviousValue={false}
                  />
                  {product.specialPrice !== null && product.regularPrice !== null ? (
                    <div className="meta-text">Regular <Price value={product.regularPrice} currency={product.currency} /></div>
                  ) : null}
                </td>
                {!isKudu && (
                  <>
                    <td className="num">
                      <Price value={product.previousSpecialPrice ?? product.previousRegularPrice} currency={product.currency} />
                    </td>
                    <td><SizeList sizes={product.sizes} currency={product.currency} /></td>
                  </>
                )}
                <td className="nowrap">{formatRiyadhDateTime(product.lastSeenAt)}</td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
    </>
  );
}
