import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Badge, EventType } from "../components/Badge";
import { DataBanner } from "../components/DataBanner";
import { DataTable } from "../components/DataTable";
import { PageHeader } from "../components/PageHeader";
import { Stat } from "../components/Stat";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { formatRiyadhDateTime } from "../lib/dateTime";

export function MarketOverviewPage() {
  const { data, error, loading } = useApi(() => api.marketOverview(), []);
  if (loading) return <LoadingState variant="metrics" />;
  if (error) return <ErrorState error={error} />;
  if (!data) return <EmptyState message="No market data." />;

  return (
    <>
      <PageHeader
        title="Market Overview"
        subtitle="Daily check-in for connected competitors. Collection is one Riyadh branch per brand."
      />
      <DataBanner freshness={data.freshness} lastUpdatedAt={data.lastUpdatedAt} />
      <div className="kpi-row">
        <Stat label="Last updated (Riyadh)" value={formatRiyadhDateTime(data.lastUpdatedAt)} />
        <Stat label="Price decreases" value={data.counts.priceDecreases} />
        <Stat label="Price increases" value={data.counts.priceIncreases} />
        <Stat label="New products" value={data.counts.newProducts} />
        <Stat label="New / ended offers" value={`${data.counts.newOffers} / ${data.counts.endedOffers}`} />
      </div>
      <div className="panel-grid">
        <div className="card">
          <h2 className="panel-title">Prioritized highlights</h2>
          {data.highlights.length === 0 ? (
            <EmptyState message="No highlight-worthy events in the current window." />
          ) : (
            <DataTable caption="Prioritized highlights across connected competitors">
              <thead>
                <tr>
                  <th className="num">Rank</th>
                  <th>Event</th>
                  <th>Item</th>
                  <th>Channel</th>
                  <th>When</th>
                </tr>
              </thead>
              <tbody>
                {data.highlights.map((item) => (
                  <tr key={item.id}>
                    <td className="num">{item.rank}</td>
                    <td><EventType value={item.type} /></td>
                    <td>
                      <Link className="linkish" to={item.href}>{item.title}</Link>
                      <div className="meta-text">{item.summary}</div>
                    </td>
                    <td>{item.channel}</td>
                    <td className="nowrap">{formatRiyadhDateTime(item.detectedAt)}</td>
                  </tr>
                ))}
              </tbody>
            </DataTable>
          )}
        </div>
        <div className="card">
          <h2 className="panel-title">Brand status</h2>
          <DataTable caption="Connected brand status summary">
            <thead>
              <tr>
                <th>Brand</th>
                <th>Health</th>
                <th>Last success</th>
                <th className="num">Products</th>
                <th className="num">Promos</th>
                <th className="num">Changes</th>
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
                  <td className="nowrap">{formatRiyadhDateTime(row.brand.lastSuccessfulRunAt)}</td>
                  <td className="num">{row.productCount ?? "—"}</td>
                  <td className="num">{row.promotionCount ?? "—"}</td>
                  <td className="num">{row.changeCount ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </DataTable>
          <p className="meta-text" style={{ marginTop: 12 }}>
            Connected: {data.connectedBrandIds.join(", ") || "none"}. Disconnected brands are not treated as healthy empty catalogs.
          </p>
        </div>
      </div>
    </>
  );
}
