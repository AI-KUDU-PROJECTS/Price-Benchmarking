import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { EventType } from "../components/Badge";
import { BrandTabs } from "../components/BrandTabs";
import { DataBanner } from "../components/DataBanner";
import { DataTable } from "../components/DataTable";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { changeHref } from "../lib/links";
import { formatRiyadhDateTime } from "../lib/dateTime";
import { clearSearchParams, setSearchParam } from "../lib/params";

const FILTER_KEYS = ["channel", "type", "from", "to"] as const;

const EVENT_OPTIONS = [
  ["", "All types"],
  ["price_increased", "Price increased"],
  ["price_decreased", "Price decreased"],
  ["product_added", "Product added"],
  ["product_removed", "Product removed"],
  ["product_not_observed", "Product not observed"],
  ["product_returned", "Product returned"],
  ["offer_started", "Offer started"],
  ["offer_ended", "Offer ended"],
  ["offer_not_observed", "Offer not observed"],
  ["offer_returned", "Offer returned"],
  ["new_in_channel", "New in channel"],
  ["availability_changed", "Availability changed"],
];

export function BrandChangesPage({ brandId }: { brandId: string }) {
  const [params, setParams] = useSearchParams();
  const query = new URLSearchParams();
  for (const key of FILTER_KEYS) {
    const value = params.get(key);
    if (value) query.set(key, value);
  }
  const suffix = query.toString() ? `?${query}` : "";
  const { data, error, loading } = useApi(() => api.changes(brandId, suffix), [brandId, suffix]);
  const hasFilters = FILTER_KEYS.some((key) => params.get(key));

  if (loading) return <LoadingState />;
  if (error) return <ErrorState error={error} />;
  if (!data) return <EmptyState message="No changes." />;

  return (
    <>
      <PageHeader title="Changes" subtitle="Source event types are preserved. Not observed is not the same as removed or ended." />
      <BrandTabs brandId={brandId} />
      <DataBanner freshness={data.meta.freshness} />
      <div className="filter-bar">
        <label className="visually-hidden" htmlFor="filter-channel">Channel</label>
        <select id="filter-channel" className="control" value={params.get("channel") || ""} onChange={(e) => setSearchParam(setParams, params, "channel", e.target.value)}>
          <option value="">All channels</option>
          <option value="pickup">Pickup</option>
          <option value="delivery">Delivery</option>
        </select>
        <label className="visually-hidden" htmlFor="filter-type">Event type</label>
        <select id="filter-type" className="control" value={params.get("type") || ""} onChange={(e) => setSearchParam(setParams, params, "type", e.target.value)}>
          {EVENT_OPTIONS.map(([value, label]) => (
            <option key={label} value={value}>{label}</option>
          ))}
        </select>
        <label className="visually-hidden" htmlFor="filter-from">From date</label>
        <input id="filter-from" type="date" className="control" value={params.get("from") || ""} onChange={(e) => setSearchParam(setParams, params, "from", e.target.value)} />
        <label className="visually-hidden" htmlFor="filter-to">To date</label>
        <input id="filter-to" type="date" className="control" value={params.get("to") || ""} onChange={(e) => setSearchParam(setParams, params, "to", e.target.value)} />
        {hasFilters ? (
          <button type="button" className="clear-filters" onClick={() => clearSearchParams(setParams, params, FILTER_KEYS)}>
            Clear filters
          </button>
        ) : null}
      </div>
      {data.items.length === 0 ? (
        <EmptyState message="No changes match these filters." />
      ) : (
        <DataTable caption={`${brandId} change events`}>
          <thead>
            <tr>
              <th>When</th>
              <th>Type</th>
              <th>Item</th>
              <th>Before</th>
              <th>After</th>
              <th className="num">%</th>
              <th>Channel</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((event) => (
              <tr key={event.id}>
                <td className="nowrap">{formatRiyadhDateTime(event.detectedAt)}</td>
                <td><EventType value={event.type} /></td>
                <td>
                  <Link className="linkish" to={changeHref(event)}>
                    {event.title || event.id}
                  </Link>
                </td>
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
