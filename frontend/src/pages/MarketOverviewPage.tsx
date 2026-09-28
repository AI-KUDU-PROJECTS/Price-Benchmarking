import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { PullRun } from "../api/types";
import { useApi } from "../api/useApi";
import { Badge, EventType } from "../components/Badge";
import { DataBanner } from "../components/DataBanner";
import { DataTable } from "../components/DataTable";
import { PageHeader } from "../components/PageHeader";
import { Stat } from "../components/Stat";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { formatRiyadhDateTime } from "../lib/dateTime";

export function MarketOverviewPage() {
  const [refreshKey, setRefreshKey] = useState(0);
  const [pullRun, setPullRun] = useState<PullRun | null>(null);
  const [starting, setStarting] = useState(false);
  const [pullError, setPullError] = useState<string | null>(null);
  const [hungerstationRun, setHungerstationRun] = useState<PullRun | null>(null);
  const [hungerstationStarting, setHungerstationStarting] = useState(false);
  const [hungerstationError, setHungerstationError] = useState<string | null>(null);
  const { data, error, loading } = useApi(() => api.marketOverview(), [refreshKey]);

  useEffect(() => {
    let active = true;
    api.pullStatus()
      .then((response) => { if (active) setPullRun(response.run); })
      .catch((reason: Error) => { if (active) setPullError(reason.message); });
    api.hungerstationPullStatus()
      .then((response) => { if (active) setHungerstationRun(response.run); })
      .catch((reason: Error) => { if (active) setHungerstationError(reason.message); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (pullRun?.status !== "running") return;
    let active = true;
    const timer = window.setInterval(() => {
      api.pullStatus()
        .then((response) => {
          if (!active) return;
          if (!response.run) {
            setPullRun(null);
            setPullError("Collection status was lost. Start a new pull to try again.");
            return;
          }
          setPullRun(response.run);
          setPullError(null);
          if (response.run.status !== "running") setRefreshKey((value) => value + 1);
        })
        .catch((reason: Error) => { if (active) setPullError(reason.message); });
    }, 2000);
    return () => { active = false; window.clearInterval(timer); };
  }, [pullRun?.runId, pullRun?.status]);

  useEffect(() => {
    if (hungerstationRun?.status !== "running") return;
    let active = true;
    const timer = window.setInterval(() => {
      api.hungerstationPullStatus()
        .then((response) => {
          if (!active) return;
          if (!response.run) {
            setHungerstationRun(null);
            setHungerstationError("HungerStation collection status was lost. Start a new pull to try again.");
            return;
          }
          setHungerstationRun(response.run);
          setHungerstationError(null);
          if (response.run.status !== "running") setRefreshKey((value) => value + 1);
        })
        .catch((reason: Error) => { if (active) setHungerstationError(reason.message); });
    }, 2000);
    return () => { active = false; window.clearInterval(timer); };
  }, [hungerstationRun?.runId, hungerstationRun?.status]);

  async function startPull() {
    setStarting(true);
    setPullError(null);
    try {
      const response = await api.startPullAll();
      setPullRun(response.run);
    } catch (reason) {
      setPullError(reason instanceof Error ? reason.message : "Could not start data collection.");
    } finally {
      setStarting(false);
    }
  }

  async function startHungerstationPull() {
    setHungerstationStarting(true);
    setHungerstationError(null);
    try {
      const response = await api.startHungerstationPull();
      setHungerstationRun(response.run);
    } catch (reason) {
      setHungerstationError(reason instanceof Error ? reason.message : "Could not start HungerStation collection.");
    } finally {
      setHungerstationStarting(false);
    }
  }
  if (loading) return <LoadingState variant="metrics" />;
  if (error) return <ErrorState error={error} />;
  if (!data) return <EmptyState message="No market data." />;

  return (
    <>
      <PageHeader
        title="Market Overview"
        subtitle="KUDU is the menu baseline; competitor collections are shown alongside it."
        extra={
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <button type="button" className="btn btn-primary" onClick={startPull} disabled={starting || pullRun?.status === "running"}>
              <RefreshCw size={18} aria-hidden="true" />
              Collect websites
            </button>
            <button type="button" className="btn btn-secondary" onClick={startHungerstationPull} disabled={hungerstationStarting || hungerstationRun?.status === "running"}>
              <RefreshCw size={18} aria-hidden="true" />
              Collect HungerStation
            </button>
          </div>
        }
      />
      {pullError && <div className="alert" data-tone="error" role="alert"><p className="alert-text">{pullError}</p></div>}
      {hungerstationError && <div className="alert" data-tone="error" role="alert"><p className="alert-text">{hungerstationError}</p></div>}
      {pullRun && (
        <section className="pull-panel" aria-label="Data collection progress">
          <div className="pull-panel-heading">
            <h2 className="panel-title">Website collection</h2>
            <span aria-live="polite"><Badge value={pullRun.status} /></span>
          </div>
          <p className="meta-text">Started {formatRiyadhDateTime(pullRun.startedAt)} · Finished {formatRiyadhDateTime(pullRun.completedAt)}</p>
          <DataTable caption="Status of the current data pull by brand">
            <thead><tr><th>Brand</th><th>Status</th><th>Started</th><th>Finished</th><th>Result</th></tr></thead>
            <tbody>
              {pullRun.brands.map((brand) => (
                <tr key={brand.id}>
                  <td>{brand.name}</td>
                  <td><Badge value={brand.status} /></td>
                  <td className="nowrap">{formatRiyadhDateTime(brand.startedAt)}</td>
                  <td className="nowrap">{formatRiyadhDateTime(brand.completedAt)}</td>
                  <td>{brand.message || "—"}</td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </section>
      )}
      {hungerstationRun && (
        <section className="pull-panel" aria-label="HungerStation collection progress">
          <div className="pull-panel-heading">
            <h2 className="panel-title">HungerStation collection</h2>
            <span aria-live="polite"><Badge value={hungerstationRun.status} /></span>
          </div>
          <p className="meta-text">Started {formatRiyadhDateTime(hungerstationRun.startedAt)} · Finished {formatRiyadhDateTime(hungerstationRun.completedAt)}</p>
          <DataTable caption="HungerStation collection status by restaurant">
            <thead><tr><th>Restaurant</th><th>Status</th><th>Started</th><th>Finished</th><th>Result</th></tr></thead>
            <tbody>
              {hungerstationRun.brands.map((brand) => (
                <tr key={brand.id}>
                  <td>{brand.name}</td>
                  <td><Badge value={brand.status} /></td>
                  <td className="nowrap">{formatRiyadhDateTime(brand.startedAt)}</td>
                  <td className="nowrap">{formatRiyadhDateTime(brand.completedAt)}</td>
                  <td>{brand.message || "—"}</td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </section>
      )}
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
