import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Badge, EventType } from "../components/Badge";
import { DataBanner } from "../components/DataBanner";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, LoadingState } from "../components/States";

export function MarketOverviewPage() {
  const { data, error, loading } = useApi(() => api.marketOverview(), []);
  if (loading) return <LoadingState />;
  if (error) return <ErrorState error={error} />;
  if (!data) return <EmptyState message="No market data." />;

  return (
    <>
      <PageHeader
        title="Market Overview"
        subtitle="Daily check-in for connected competitors. Collection is one Riyadh branch per brand."
      />
      <DataBanner freshness={data.freshness} lastUpdatedAt={data.lastUpdatedAt} />
      <div className="grid metrics">
        <Metric label="Last updated" value={data.lastUpdatedAt || "—"} />
        <Metric label="Price decreases" value={data.counts.priceDecreases} />
        <Metric label="Price increases" value={data.counts.priceIncreases} />
        <Metric label="New products" value={data.counts.newProducts} />
        <Metric label="New / ended offers" value={`${data.counts.newOffers} / ${data.counts.endedOffers}`} />
      </div>
      <div className="grid two" style={{ marginTop: 16 }}>
        <div className="card">
          <h2>Prioritized highlights</h2>
          {data.highlights.length === 0 ? (
            <EmptyState message="No highlight-worthy events in the current window." />
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Rank</th>
                    <th>Event</th>
                    <th>Item</th>
                    <th>Channel</th>
                    <th>When</th>
                  </tr>
                </thead>
                <tbody>
                  {data.highlights.map((item) => (
                    <tr key={item.id}>
                      <td>{item.rank}</td>
                      <td><EventType value={item.type} /></td>
                      <td>
                        <Link className="linkish" to={item.href}>{item.title}</Link>
                        <div className="subnav-note">{item.summary}</div>
                      </td>
                      <td>{item.channel}</td>
                      <td>{item.detectedAt}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        <div className="card">
          <h2>Brand status</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Brand</th>
                  <th>Health</th>
                  <th>Last success</th>
                  <th>Products</th>
                  <th>Promos</th>
                  <th>Changes</th>
                </tr>
              </thead>
              <tbody>
                {data.brands.map((row) => (
                  <tr key={row.brand.id}>
                    <td>
                      {row.brand.health === "disconnected" ? (
                        row.brand.name
                      ) : (
                        <Link className="linkish" to={`/competitors/${row.brand.id}`}>{row.brand.name}</Link>
                      )}
                    </td>
                    <td><Badge value={row.brand.health} /></td>
                    <td>{row.brand.lastSuccessfulRunAt || "—"}</td>
                    <td>{row.productCount ?? "—"}</td>
                    <td>{row.promotionCount ?? "—"}</td>
                    <td>{row.changeCount ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="subnav-note" style={{ marginTop: 12 }}>
            Connected: {data.connectedBrandIds.join(", ") || "none"}. Disconnected brands are not treated as healthy empty catalogs.
          </p>
        </div>
      </div>
    </>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="card">
      <div className="metric-value">{value}</div>
      <div className="metric-label">{label}</div>
    </div>
  );
}
