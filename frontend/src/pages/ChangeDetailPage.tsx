import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { BackLink } from "../components/BackLink";
import { EventType } from "../components/Badge";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { productHref, promotionHref } from "../lib/links";
import { formatRiyadhDateTime } from "../lib/dateTime";

export function ChangeDetailPage() {
  const { changeId = "" } = useParams();
  const { data, error, loading } = useApi(() => api.change(changeId), [changeId]);

  if (loading) return <LoadingState variant="detail" />;
  if (error) return <ErrorState error={error} />;
  if (!data) return <EmptyState message="Change not found." />;

  return (
    <>
      <div className="page-header-back">
        <BackLink label="Back to changes" fallback="/changes" />
      </div>
      <PageHeader title={data.title || data.type} subtitle={formatRiyadhDateTime(data.detectedAt)} />
      <div className="card detail-card">
        <div className="stack">
          <div>
            <EventType value={data.type} /> <span className="meta-text">{data.channel}</span>
          </div>
          <div className="field-row"><span className="field-label">Before</span><span className="field-value">{data.beforeValue || "—"}</span></div>
          <div className="field-row"><span className="field-label">After</span><span className="field-value">{data.afterValue || "—"}</span></div>
          <div className="field-row"><span className="field-label">Percent</span><span className="field-value">{data.percentageChange === null ? "—" : `${data.percentageChange}%`}</span></div>
          <div className="field-row"><span className="field-label">Location</span><span className="field-value">{data.location || "—"}</span></div>
          <div className="field-row"><span className="field-label">Run</span><span className="field-value">{data.sourceRunId || "—"}</span></div>
        </div>
        {data.productId || data.promotionId ? (
          <div className="action-row">
            {data.productId ? (
              <Link className="btn btn-secondary btn-sm" to={productHref(data.brandId, data.productId)}>
                Product history
              </Link>
            ) : null}
            {data.promotionId ? (
              <Link className="btn btn-secondary btn-sm" to={promotionHref(data.brandId, data.promotionId)}>
                Promotion detail
              </Link>
            ) : null}
          </div>
        ) : null}
      </div>
    </>
  );
}
