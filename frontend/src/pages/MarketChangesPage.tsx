import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { EventType } from "../components/Badge";
import { DataBanner } from "../components/DataBanner";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { changeHref } from "../lib/links";

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
  for (const key of ["brand", "channel", "type", "from", "to"] as const) {
    const value = params.get(key);
    if (value) query.set(key, value);
  }
  const suffix = query.toString() ? `?${query}` : "";
  const { data, error, loading } = useApi(() => api.marketChanges(suffix), [suffix]);

  if (loading) return <LoadingState />;
  if (error) return <ErrorState error={error} />;
  if (!data) return <EmptyState message="No market changes." />;

  return (
    <>
      <PageHeader title="Market Changes" subtitle="Chronological activity across connected competitors." />
      <DataBanner freshness={data.meta.freshness} />
      <div className="filters">
        <select value={params.get("brand") || ""} onChange={(event) => write(setParams, params, "brand", event.target.value)}>
          {BRANDS.map(([value, label]) => <option key={value || "all"} value={value}>{label}</option>)}
        </select>
        <select value={params.get("channel") || ""} onChange={(event) => write(setParams, params, "channel", event.target.value)}>
          <option value="">All channels</option>
          <option value="pickup">Pickup</option>
          <option value="delivery">Delivery</option>
        </select>
        <select value={params.get("type") || ""} onChange={(event) => write(setParams, params, "type", event.target.value)}>
          {EVENT_TYPES.map(([value, label]) => <option key={value || "all"} value={value}>{label}</option>)}
        </select>
        <input type="date" value={params.get("from") || ""} onChange={(event) => write(setParams, params, "from", event.target.value)} />
        <input type="date" value={params.get("to") || ""} onChange={(event) => write(setParams, params, "to", event.target.value)} />
      </div>
      {data.items.length === 0 ? (
        <EmptyState message="No changes match these filters." />
      ) : (
        <div className="card table-wrap">
          <table>
            <thead>
              <tr><th>When</th><th>Brand</th><th>Type</th><th>Item</th><th>Before</th><th>After</th><th>%</th><th>Channel</th></tr>
            </thead>
            <tbody>
              {data.items.map((event) => (
                <tr key={`${event.brandId}-${event.id}`}>
                  <td>{event.detectedAt}</td>
                  <td>{labelForBrand(event.brandId)}</td>
                  <td><EventType value={event.type} /></td>
                  <td><Link className="linkish" to={changeHref(event)}>{event.title || event.id}</Link></td>
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

function write(setParams: (params: URLSearchParams) => void, params: URLSearchParams, key: string, value: string) {
  const next = new URLSearchParams(params);
  if (value) next.set(key, value);
  else next.delete(key);
  setParams(next);
}

function labelForBrand(id: string) {
  return BRANDS.find(([value]) => value === id)?.[1] || id;
}
