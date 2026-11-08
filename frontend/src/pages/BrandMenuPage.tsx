import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { Channel, Product } from "../api/types";
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

const channels: { id: Channel; label: string }[] = [
  { id: "pickup", label: "Pickup" },
  { id: "delivery", label: "Delivery" },
  { id: "hungerstation", label: "HungerStation" },
];

function ChannelPrice({ product, label }: { product?: Product; label: string }) {
  if (!product) return <Price value={null} />;
  return (
    <div className="menu-channel-price">
      <Link className="linkish" to={productHref(product.brandId, product.id)}
        aria-label={`${label} details for ${product.nameEn || product.nameAr || product.id}`}>
        <Price value={product.specialPrice ?? product.regularPrice} currency={product.currency} />
      </Link>
      {product.specialPrice !== null && product.regularPrice !== null && (
        <div className="meta-text">Regular <Price value={product.regularPrice} currency={product.currency} /></div>
      )}
      {product.sizes.length > 0 && <SizeList sizes={product.sizes} currency={product.currency} />}
      {product.status !== "active" && <Badge value={product.status} />}
      {product.isPublished === false && <Badge value="unpublished" />}
      {product.availability === false && <Badge value="unavailable" />}
    </div>
  );
}

export function BrandMenuPage({ brandId }: { brandId: string }) {
  const [params, setParams] = useSearchParams();
  const isKudu = brandId === "kudu";
  // Keep KUDU's Delivery default and use an explicit value for comparisons.
  const selectedChannel = params.get("channel") || (isKudu ? "delivery" : "all");
  const channel = selectedChannel === "all" ? "" : selectedChannel;
  const comparing = channel === "";
  const q = params.get("q") || "";
  const query = new URLSearchParams();
  if (channel) query.set("channel", channel);
  if (q) query.set("q", q);
  if (params.get("page")) query.set("page", params.get("page") as string);
  const suffix = query.toString() ? `?${query}` : "";
  const { data, error, loading } = useApi(() => api.menu(brandId, suffix), [brandId, suffix], { keepPreviousData: true });

  if (loading && !data) return <LoadingState />;
  if (error) return <ErrorState error={error} />;
  if (!data) return <EmptyState message="No products." />;

  return (
    <>
      <PageHeader
        title={isKudu ? "KUDU menu" : "Menu"}
        subtitle={comparing
          ? "Compare Pickup, Delivery and HungerStation prices for each product. — means no price is available."
          : isKudu
          ? channel === "hungerstation"
            ? "HungerStation menu from the KUDU integration API · images reused from the main menu where the item matches"
            : "Production menu · template 1 · prices and images from the latest saved collection"
          : "Latest successful collection. Missing prices stay blank."}
      />
      <BrandTabs brandId={brandId} />
      <DataBanner freshness={data.meta.freshness} lastUpdatedAt={isKudu && !comparing ? data.items[0]?.product.observedAt : undefined} />
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
          <option value="all">All channels</option>
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
                {comparing ? channels.map(({ id, label }) => (
                  <th key={id} className="num">{label}</th>
                )) : <>
                  <th>Channel</th>
                  <th className="num">{isKudu ? "Price" : "Current"}</th>
                  {!isKudu && <th className="num">Previous</th>}
                  {!isKudu && <th>Sizes</th>}
                  <th>{isKudu ? "Collected" : "Last seen"}</th>
                </>}
              </tr>
            </thead>
            <tbody>
              {data.items.map((row) => {
                const product = comparing ? row.product : row.channels[channel as Channel];
                // A channel switch can briefly retain the previous response.
                if (!product) return null;
                const image = product.imageUrl || Object.values(row.channels).find((item) => item?.imageUrl)?.imageUrl;
                return <tr key={row.id}>
                  <td><ProductImage src={image} alt={product.nameEn || ""} /></td>
                  <td>
                    <Link className="linkish" to={productHref(brandId, product.id)}>
                      {product.nameEn || product.nameAr || product.id}
                    </Link>
                    <div className="meta-text">{product.nameAr || "Arabic name unavailable"}</div>
                    {!comparing && <>
                      <Badge value={product.isPublished === false ? "unpublished" : product.status} />
                      {product.availability === false && <Badge value="unavailable" />}
                    </>}
                  </td>
                  <td>{product.category || "—"}{isKudu && product.categoryAr && <div className="meta-text">{product.categoryAr}</div>}</td>
                  {comparing ? channels.map(({ id, label }) => (
                    <td key={id} className="num"><ChannelPrice product={row.channels[id]} label={label} /></td>
                  )) : <>
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
                  </>}
                </tr>
              })}
            </tbody>
          </DataTable>
        )}
        <Pager meta={data.meta} onPage={(page) => setPageParam(setParams, params, page)} />
      </div>
    </>
  );
}
