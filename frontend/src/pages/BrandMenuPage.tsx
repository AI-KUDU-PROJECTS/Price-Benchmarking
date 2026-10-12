import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Badge } from "../components/Badge";
import { BrandTabs } from "../components/BrandTabs";
import { DataBanner } from "../components/DataBanner";
import { DataTable } from "../components/DataTable";
import { PageHeader } from "../components/PageHeader";
import { Pager } from "../components/Pager";
import { Price } from "../components/Price";
import { ProductImage } from "../components/ProductImage";
import { SearchField } from "../components/SearchField";
import { SizeList } from "../components/SizeList";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { productHref } from "../lib/links";
import { formatRiyadhDateTime } from "../lib/dateTime";
import { setPageParam, setSearchParam } from "../lib/params";

export function BrandMenuPage({ brandId }: { brandId: string }) {
  const [params, setParams] = useSearchParams();
  const isKudu = brandId === "kudu";
  // KUDU opens on Delivery when the URL has no channel, so "All channels"
  // needs an explicit value there; competitors use an empty value.
  const allChannels = isKudu ? "all" : "";
  const selectedChannel = params.get("channel") || (isKudu ? "delivery" : "");
  const channel = selectedChannel === "all" ? "" : selectedChannel;
  const q = params.get("q") || "";
  const query = new URLSearchParams();
  if (channel) query.set("channel", channel);
  if (q) query.set("q", q);
  if (params.get("page")) query.set("page", params.get("page") as string);
  const suffix = query.toString() ? `?${query}` : "";
  const { data, error, loading } = useApi(() => api.products(brandId, suffix), [brandId, suffix], { keepPreviousData: true });

  if (loading && !data) return <LoadingState />;
  if (error) return <ErrorState error={error} />;
  if (!data) return <EmptyState message="No products." />;

  return (
    <>
      <PageHeader
        title={isKudu ? "KUDU menu" : "Menu"}
        subtitle={isKudu
          ? channel === "hungerstation"
            ? "HungerStation menu from the KUDU integration API · images reused from the main menu where the item matches"
            : channel === ""
              ? "All channels · production menu (delivery, pickup) and the HungerStation menu from the KUDU integration API"
              : "Production menu · template 1 · prices and images from the latest saved collection"
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
          value={selectedChannel}
          onChange={(e) => setSearchParam(setParams, params, "channel", e.target.value)}
        >
          <option value={allChannels}>All channels</option>
          <option value="pickup">Pickup</option>
          <option value="delivery">Delivery</option>
          <option value="hungerstation">HungerStation</option>
        </select>
      </div>
      <div className="results" aria-busy={loading}>
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
                    {product.availability === false && <Badge value="unavailable" />}
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
        <Pager meta={data.meta} onPage={(page) => setPageParam(setParams, params, page)} />
      </div>
    </>
  );
}
