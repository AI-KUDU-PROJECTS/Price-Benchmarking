import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Badge, EventType } from "../components/Badge";
import { BrandTabs } from "../components/BrandTabs";
import { DataBanner } from "../components/DataBanner";
import { PageHeader } from "../components/PageHeader";
import { Stat } from "../components/Stat";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { changeHref } from "../lib/links";
import { formatRiyadhDateTime } from "../lib/dateTime";

export function BrandOverviewPage({ brandId }: { brandId: string }) {
  const { data, error, loading } = useApi(() => api.brandOverview(brandId), [brandId]);
  if (loading) return <LoadingState variant="metrics" />;
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
      <div className="kpi-row">
        <Stat label="Last successful update (Riyadh)" value={formatRiyadhDateTime(brand.lastSuccessfulRunAt)} />
        <Stat label="Items in latest success" value={data.productCount} />
        <Stat label="Active promotions" value={data.promotionCount} />
        <Stat label="Recent change rows" value={data.recentChanges.length} />
        <div className="kpi">
          <div className="kpi-label">Run health</div>
          <div className="kpi-runs">
            {data.runs.slice(0, 4).map((run) => (
              <div key={run.id} className="meta-text">
                {run.channel} <Badge value={run.status} /> {formatRiyadhDateTime(run.startedAt)}
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="panel-grid">
        <div className="card">
          <h2 className="panel-title">Highlights</h2>
          {data.highlights.length === 0 ? (
            <EmptyState message="No ranked highlights for this window." />
          ) : (
            <div className="table-scroll">
              <table>
                <tbody>
                  {data.highlights.map((item) => (
                    <tr key={item.id}>
                      <td><EventType value={item.type} /></td>
                      <td>
                        <Link className="linkish" to={item.href}>{item.title}</Link>
                      </td>
                      <td className="nowrap">{formatRiyadhDateTime(item.detectedAt)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        <div className="card">
          <h2 className="panel-title">Recent changes</h2>
          <div className="stack">
            {data.recentChanges.slice(0, 12).map((event) => (
              <div key={event.id}>
                <EventType value={event.type} />{" "}
                <Link className="linkish" to={changeHref(event)}>{event.title || event.type}</Link>
                <div className="meta-text">{event.channel} · {formatRiyadhDateTime(event.detectedAt)}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}
