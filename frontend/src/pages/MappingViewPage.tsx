import { Pencil } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { PriceMapping } from "../api/types";
import { BackLink } from "../components/BackLink";
import { MappingFlowCanvas } from "../components/MappingFlowCanvas";
import { MappingItemInspector } from "../components/MappingItemInspector";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { formatRiyadhDateTime } from "../lib/dateTime";
import {
  channelLabel,
  flowProductKey,
  flowProductName,
  signedMoney,
  type FlowProduct,
} from "../lib/playground";

function insightFor(mapping: PriceMapping): string {
  const comparable = mapping.competitorItems.filter(
    (item) => !item.missing && item.differenceAmount !== null,
  );
  const unavailable = mapping.competitorItems.length - comparable.length;

  if (comparable.length === 0) {
    return `No current price comparison is available.${unavailable > 0 ? ` ${unavailable} mapped ${unavailable === 1 ? "item is" : "items are"} unavailable.` : ""}`;
  }

  const kuduCheaper = comparable.filter((item) => (item.differenceAmount as number) > 0).length;
  const kuduMoreExpensive = comparable.filter((item) => (item.differenceAmount as number) < 0).length;
  const equal = comparable.length - kuduCheaper - kuduMoreExpensive;
  const closest = comparable.reduce((current, item) =>
    Math.abs(item.differenceAmount as number) < Math.abs(current.differenceAmount as number)
      ? item
      : current,
  );

  const parts = [
    `KUDU is cheaper than ${kuduCheaper} of ${comparable.length} comparable ${comparable.length === 1 ? "item" : "items"}`,
  ];
  if (kuduMoreExpensive > 0) parts.push(`more expensive than ${kuduMoreExpensive}`);
  if (equal > 0) parts.push(`equal to ${equal}`);

  let summary = `${parts.join(", ")}. Closest price: ${closest.brandName} ${flowProductName(closest)} at ${signedMoney(closest.differenceAmount, closest.currency)}.`;
  if (unavailable > 0) {
    summary += ` ${unavailable} mapped ${unavailable === 1 ? "item is" : "items are"} unavailable.`;
  }
  return summary;
}

export function MappingViewPage() {
  const { mappingId = "" } = useParams();
  const [mapping, setMapping] = useState<PriceMapping | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setNotFound(false);
    api.playgroundMapping(mappingId)
      .then((result) => {
        if (cancelled) return;
        setMapping(result);
        setSelectedKey(flowProductKey(result.kuduItem));
        setLoading(false);
      })
      .catch((caught: Error) => {
        if (cancelled) return;
        if (caught instanceof ApiError && caught.status === 404) setNotFound(true);
        else setError(caught);
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [mappingId]);

  const selectedItem = useMemo<FlowProduct | null>(() => {
    if (!mapping || !selectedKey) return null;
    if (flowProductKey(mapping.kuduItem) === selectedKey) return mapping.kuduItem;
    return mapping.competitorItems.find((item) => flowProductKey(item) === selectedKey) || null;
  }, [mapping, selectedKey]);

  if (loading) return <LoadingState variant="detail" />;
  if (notFound) {
    return (
      <EmptyState
        message="This mapping could not be found. It may have been deleted."
        action={<Link className="btn btn-primary" to="/playground">Back to Playground</Link>}
      />
    );
  }
  if (error) return <ErrorState error={error} />;
  if (!mapping) return <EmptyState message="Mapping not found." />;

  return (
    <>
      <div className="page-header-back">
        <BackLink label="Back to Playground" fallback="/playground" />
      </div>
      <PageHeader
        title={mapping.name}
        subtitle={`${channelLabel(mapping.channel)} · Updated ${formatRiyadhDateTime(mapping.updatedAt)}`}
        extra={(
          <Link className="btn btn-primary" to={`/playground?edit=${encodeURIComponent(mapping.id)}`}>
            <Pencil size={16} aria-hidden="true" />
            Edit mapping
          </Link>
        )}
      />

      <div className="mapping-insight" role="status">
        <strong>Live comparison</strong>
        <span>{insightFor(mapping)}</span>
      </div>

      <section className="mapping-view-section" aria-labelledby="mapping-flow-title">
        <div className="section-heading">
          <div>
            <h2 className="section-title" id="mapping-flow-title">Mapping flow</h2>
            <p className="section-description">Drag nodes to explore the relationship. Select any item to inspect its latest details.</p>
          </div>
          <span className="meta-text">{mapping.competitorItems.length} competitor {mapping.competitorItems.length === 1 ? "item" : "items"}</span>
        </div>
        <MappingFlowCanvas
          mode="view"
          kuduItem={mapping.kuduItem}
          competitorItems={mapping.competitorItems}
          selectedKey={selectedKey}
          onSelect={(item) => setSelectedKey(flowProductKey(item))}
        />
      </section>

      <MappingItemInspector item={selectedItem} kuduItem={mapping.kuduItem} />
    </>
  );
}
