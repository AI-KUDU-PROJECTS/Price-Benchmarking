import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { EventType } from "../components/Badge";
import { DataBanner } from "../components/DataBanner";
import { DataTable } from "../components/DataTable";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { changeHref } from "../lib/links";
import { formatRiyadhDateTime } from "../lib/dateTime";
import { clearSearchParams, setSearchParam } from "../lib/params";

const FILTER_KEYS = ["brand", "channel", "type", "from", "to"] as const;

const BRANDS = [
  ["", "All brands"],
  ["kfc", "KFC"],
  ["hardees", "Hardee's"],
  ["burger-king", "Burger King"],
  ["herfy", "Herfy"],
];

const EVENT_TYPES = [
  ["", "All types"],
  ["price_increased", "Price increased"],
  ["price_decreased", "Price decreased"],
  ["product_added", "Product added"],
  ["product_removed", "Product removed"],
  ["offer_started", "Offer started"],
  ["offer_ended", "Offer ended"],
  ["availability_changed", "Availability changed"],
];

export function MarketChangesPage() {
  const [params, setParams] = useSearchParams();
  const query = new URLSearchParams();
  for (const key of FILTER_KEYS) {
    const value = params.get(key);
    if (value) query.set(key, value);
  }
  const suffix = query.toString() ? `?${query}` : "";
  const { data, error, loading } = useApi(() => api.marketChanges(suffix), [suffix]);
  const hasFilters = FILTER_KEYS.some((key) => params.get(key));

  if (loading) return <LoadingState />;
  if (error) return <ErrorState error={error} />;
  if (!data) return <EmptyState message="No market changes." />;

  return (
    <>
      <PageHeader title="Market Changes" subtitle="Chronological activity across connected competitors." />
      <DataBanner freshness={data.meta.freshness} />
      <div className="filter-bar">
        <label className="visually-hidden" htmlFor="filter-brand">Brand</label>
        <select id="filter-brand" className="control" value={params.get("brand") || ""} onChange={(event) => setSearchParam(setParams, params, "brand", event.target.value)}>
          {BRANDS.map(([value, label]) => <option key={value || "all"} value={value}>{label}</option>)}
        </select>
        <label className="visually-hidden" htmlFor="filter-channel">Channel</label>
        <select id="filter-channel" className="control" value={params.get("channel") || ""} onChange={(event) => setSearchParam(setParams, params, "channel", event.target.value)}>
          <option value="">All channels</option>
          <option value="pickup">Pickup</option>
          <option value="delivery">Delivery</option>
          <option value="hungerstation">HungerStation</option>
        </select>
        <label className="visually-hidden" htmlFor="filter-type">Event type</label>
        <select id="filter-type" className="control" value={params.get("type") || ""} onChange={(event) => setSearchParam(setParams, params, "type", event.target.value)}>
          {EVENT_TYPES.map(([value, label]) => <option key={value || "all"} value={value}>{label}</option>)}
        </select>
        <label className="visually-hidden" htmlFor="filter-from">From date</label>
        <input id="filter-from" type="date" className="control" value={params.get("from") || ""} onChange={(event) => setSearchParam(setParams, params, "from", event.target.value)} />
        <label className="visually-hidden" htmlFor="filter-to">To date</label>
        <input id="filter-to" type="date" className="control" value={params.get("to") || ""} onChange={(event) => setSearchParam(setParams, params, "to", event.target.value)} />
        {hasFilters ? (
          <button type="button" className="clear-filters" onClick={() => clearSearchParams(setParams, params, FILTER_KEYS)}>
            Clear filters
          </button>
        ) : null}
      </div>
      {data.items.length === 0 ? (
        <EmptyState message="No changes match these filters." />
      ) : (
        <DataTable caption="Market-wide change events">
          <thead>
            <tr><th>When</th><th>Brand</th><th>Type</th><th>Item</th><th>Before</th><th>After</th><th className="num">%</th><th>Channel</th></tr>
          </thead>
          <tbody>
            {data.items.map((event) => (
              <tr key={`${event.brandId}-${event.id}`}>
                <td className="nowrap">{formatRiyadhDateTime(event.detectedAt)}</td>
                <td>{labelForBrand(event.brandId)}</td>
                <td><EventType value={event.type} /></td>
                <td><Link className="linkish" to={changeHref(event)}>{event.title || event.id}</Link></td>
                <td><span className="cell-clip" title={event.beforeValue || undefined}>{event.beforeValue || "—"}</span></td>
                <td><span className="cell-clip" title={event.afterValue || undefined}>{event.afterValue || "—"}</span></td>
                <td className="num">{event.percentageChange === null ? "—" : `${event.percentageChange}%`}</td>
                <td className="nowrap">{event.channel}</td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
    </>
  );
}

function labelForBrand(id: string) {
  return BRANDS.find(([value]) => value === id)?.[1] || id;
}
