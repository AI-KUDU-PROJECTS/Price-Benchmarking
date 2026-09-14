import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { EventType } from "../components/Badge";
import { BrandTabs } from "../components/BrandTabs";
import { DataBanner } from "../components/DataBanner";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { changeHref } from "../lib/links";

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
  for (const key of ["channel", "type", "from", "to"] as const) {
    const value = params.get(key);
    if (value) query.set(key, value);
  }
  const suffix = query.toString() ? `?${query}` : "";
  const { data, error, loading } = useApi(() => api.changes(brandId, suffix), [brandId, suffix]);

  if (loading) return <LoadingState />;
  if (error) return <ErrorState error={error} />;
  if (!data) return <EmptyState message="No changes." />;

  return (
    <>
      <PageHeader title="Changes" subtitle="Source event types are preserved. Not observed is not the same as removed or ended." />
      <BrandTabs brandId={brandId} />
      <DataBanner freshness={data.meta.freshness} />
      <div className="filters">
        <select value={params.get("channel") || ""} onChange={(e) => write(setParams, params, "channel", e.target.value)}>
          <option value="">All channels</option>
          <option value="pickup">Pickup</option>
          <option value="delivery">Delivery</option>
        </select>
        <select value={params.get("type") || ""} onChange={(e) => write(setParams, params, "type", e.target.value)}>
          {EVENT_OPTIONS.map(([value, label]) => (
            <option key={label} value={value}>{label}</option>
          ))}
        </select>
        <input type="date" value={params.get("from") || ""} onChange={(e) => write(setParams, params, "from", e.target.value)} />
        <input type="date" value={params.get("to") || ""} onChange={(e) => write(setParams, params, "to", e.target.value)} />
      </div>
      {data.items.length === 0 ? (
        <EmptyState message="No changes match these filters." />
      ) : (
        <div className="card table-wrap">
          <table>
            <thead>
              <tr>
                <th>When</th>
                <th>Type</th>
                <th>Item</th>
                <th>Before</th>
                <th>After</th>
                <th>%</th>
                <th>Channel</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((event) => (
                <tr key={event.id}>
                  <td>{event.detectedAt}</td>
                  <td><EventType value={event.type} /></td>
                  <td>
                    <Link className="linkish" to={changeHref(event)}>
                      {event.title || event.id}
                    </Link>
                  </td>
                  <td>{event.beforeValue || "—"}</td>
                  <td>{event.afterValue || "—"}</td>
                  <td>{event.percentageChange === null ? "—" : `${event.percentageChange}%`}</td>
                  <td>{event.channel}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function write(
  setParams: (p: URLSearchParams) => void,
  params: URLSearchParams,
  key: string,
  value: string,
) {
  const next = new URLSearchParams(params);
  if (value) next.set(key, value);
  else next.delete(key);
  setParams(next);
}
