import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Badge, EventType } from "../components/Badge";
import { BrandTabs } from "../components/BrandTabs";
import { DataBanner } from "../components/DataBanner";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { changeHref } from "../lib/links";

export function BrandOverviewPage({ brandId }: { brandId: string }) {
  const { data, error, loading } = useApi(() => api.brandOverview(brandId), [brandId]);
  if (loading) return <LoadingState />;
  if (error) return <ErrorState error={error} />;
  if (!data) return <EmptyState message="No brand data." />;
  const { brand } = data;

  return (
    <>
      <PageHeader
        title={`${brand.name} overview`}
        subtitle={brand.locationLabel || "One verified Riyadh branch"}
        extra={<Badge value={brand.health} />}
      />
      <BrandTabs brandId={brandId} />
      <DataBanner freshness={brand.dataFreshness} health={brand.health} lastUpdatedAt={brand.lastSuccessfulRunAt} />
      <div className="grid metrics">
        <div className="card">
          <div className="metric-value">{brand.lastSuccessfulRunAt || "—"}</div>
          <div className="metric-label">Last successful update</div>
        </div>
        <div className="card">
          <div className="metric-value">{data.productCount}</div>
          <div className="metric-label">Items in latest success</div>
        </div>
        <div className="card">
          <div className="metric-value">{data.promotionCount}</div>
          <div className="metric-label">Active promotions</div>
        </div>
        <div className="card">
          <div className="metric-value">{data.recentChanges.length}</div>
          <div className="metric-label">Recent change rows</div>
        </div>
        <div className="card">
          <div className="metric-label">Run health</div>
          {data.runs.slice(0, 4).map((run) => (
            <div key={run.id} className="subnav-note">
              {run.channel} <Badge value={run.status} /> {run.startedAt}
            </div>
          ))}
        </div>
      </div>
      <div className="grid two" style={{ marginTop: 16 }}>
        <div className="card">
          <h2>Highlights</h2>
          {data.highlights.length === 0 ? (
            <EmptyState message="No ranked highlights for this window." />
          ) : (
            <table>
              <tbody>
                {data.highlights.map((item) => (
                  <tr key={item.id}>
                    <td><EventType value={item.type} /></td>
                    <td>
                      <Link className="linkish" to={item.href}>{item.title}</Link>
                    </td>
                    <td>{item.detectedAt}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="card">
          <h2>Recent changes</h2>
          {data.recentChanges.slice(0, 12).map((event) => (
            <div key={event.id} style={{ marginBottom: 8 }}>
              <EventType value={event.type} />{" "}
              <Link className="linkish" to={changeHref(event)}>{event.title || event.type}</Link>
              <div className="subnav-note">{event.channel} · {event.detectedAt}</div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
