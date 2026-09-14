import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { EventType } from "../components/Badge";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { productHref, promotionHref } from "../lib/links";

export function ChangeDetailPage() {
  const { changeId = "" } = useParams();
  const { data, error, loading } = useApi(() => api.change(changeId), [changeId]);

  if (loading) return <LoadingState />;
  if (error) return <ErrorState error={error} />;
  if (!data) return <EmptyState message="Change not found." />;

  return (
    <>
      <PageHeader title={data.title || data.type} subtitle={data.detectedAt} />
      <div className="card" style={{ maxWidth: 640 }}>
        <p className="detail-meta"><EventType value={data.type} /> <span>{data.channel}</span></p>
        <p>Before: {data.beforeValue || "—"}</p>
        <p>After: {data.afterValue || "—"}</p>
        <p>Percent: {data.percentageChange === null ? "—" : `${data.percentageChange}%`}</p>
        <p>Location: {data.location || "—"}</p>
        <p>Run: {data.sourceRunId || "—"}</p>
        {data.productId ? (
          <p>
            <Link className="linkish" to={productHref(data.brandId, data.productId)}>Product history</Link>
          </p>
        ) : null}
        {data.promotionId ? (
          <p>
            <Link className="linkish" to={promotionHref(data.brandId, data.promotionId)}>Promotion detail</Link>
          </p>
        ) : null}
      </div>
    </>
  );
}
