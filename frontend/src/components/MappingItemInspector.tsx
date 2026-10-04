import { AlertTriangle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { Product } from "../api/types";
import {
  comparePrices,
  comparisonCopy,
  flowProductKey,
  flowProductName,
  signedMoney,
  signedPercent,
  type FlowProduct,
} from "../lib/playground";
import { formatRiyadhDateTime } from "../lib/dateTime";
import { Badge } from "./Badge";
import { Price } from "./Price";
import { ProductImage } from "./ProductImage";
import { SizeList } from "./SizeList";

interface DetailState {
  key: string | null;
  product: Product | null;
  loading: boolean;
  error: Error | null;
}

function yesNo(value: boolean): string {
  return value ? "Yes" : "No";
}

function DetailRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="field-row">
      <span className="field-label">{label}</span>
      <span className="field-value">{children}</span>
    </div>
  );
}

export function MappingItemInspector({
  item,
  kuduItem,
  id = "mapping-item-details",
}: {
  item: FlowProduct | null;
  kuduItem: FlowProduct | null;
  id?: string;
}) {
  const cache = useRef(new Map<string, Product>());
  const [retry, setRetry] = useState(0);
  const [state, setState] = useState<DetailState>({
    key: null,
    product: null,
    loading: false,
    error: null,
  });
  const key = item ? flowProductKey(item) : null;

  useEffect(() => {
    if (!item || item.missing) {
      setState({ key, product: null, loading: false, error: null });
      return undefined;
    }

    const cached = cache.current.get(key as string);
    if (cached) {
      setState({ key, product: cached, loading: false, error: null });
      return undefined;
    }

    let cancelled = false;
    setState({ key, product: null, loading: true, error: null });
    api.product(item.brandId, item.productId)
      .then((product) => {
        if (cancelled) return;
        cache.current.set(key as string, product);
        setState({ key, product, loading: false, error: null });
      })
      .catch((error: Error) => {
        if (cancelled) return;
        setState({ key, product: null, loading: false, error });
      });

    return () => {
      cancelled = true;
    };
  }, [item, key, retry]);

  if (!item) {
    return (
      <section className="mapping-item-inspector" id={id} aria-labelledby={`${id}-title`}>
        <h3 className="panel-title" id={`${id}-title`}>Selected item details</h3>
        <div className="inline-empty">Choose a node to inspect its current product details.</div>
      </section>
    );
  }

  const name = flowProductName(item);
  const comparison = item.brandId === "kudu" ? null : comparePrices(item, kuduItem);

  if (item.missing) {
    return (
      <section className="mapping-item-inspector" id={id} aria-labelledby={`${id}-title`}>
        <div className="mapping-detail-heading">
          <ProductImage src={item.imageUrl} alt={name} large />
          <div>
            <span className="mapping-node-eyebrow">{item.brandName}</span>
            <h3 className="panel-title" id={`${id}-title`} dir="auto">{name}</h3>
            <span className="status-pill" data-tone="warning">No longer available</span>
          </div>
        </div>
        <div className="inline-empty">
          This mapped item is no longer present in the latest source data. Its saved fallback name remains in the flow, and no old price is used.
        </div>
      </section>
    );
  }

  const loadingCurrentItem = state.key !== key || state.loading;
  if (loadingCurrentItem) {
    return (
      <section className="mapping-item-inspector" id={id} aria-labelledby={`${id}-title`} aria-busy="true">
        <h3 className="panel-title" id={`${id}-title`}>Loading {name}</h3>
        <div className="mapping-detail-skeleton" role="status">
          <span className="skeleton-block skeleton-row short" />
          <span className="skeleton-block skeleton-row" />
          <span className="skeleton-block skeleton-row" />
        </div>
      </section>
    );
  }

  if (state.error) {
    return (
      <section className="mapping-item-inspector" id={id} aria-labelledby={`${id}-title`}>
        <h3 className="panel-title" id={`${id}-title`}>Selected item details</h3>
        <div className="alert" data-tone="error" role="alert">
          <AlertTriangle size={18} aria-hidden="true" />
          <div className="alert-text">
            <strong>Could not load {name}.</strong> {state.error.message}
          </div>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => {
              cache.current.delete(key as string);
              setRetry((current) => current + 1);
            }}
          >
            Retry
          </button>
        </div>
      </section>
    );
  }

  const product = state.product;
  if (!product) return null;
  const effectivePrice = product.specialPrice ?? product.regularPrice;

  return (
    <section className="mapping-item-inspector" id={id} aria-labelledby={`${id}-title`}>
      <div className="mapping-detail-heading">
        <ProductImage src={product.imageUrl} alt={name} large />
        <div>
          <span className="mapping-node-eyebrow">{item.brandName}</span>
          <h3 className="panel-title" id={`${id}-title`} dir="auto">{product.nameEn || product.nameAr || name}</h3>
          {product.nameAr && product.nameEn ? (
            <p className="meta-text" dir="auto">{product.nameAr}</p>
          ) : null}
          <div className="mapping-detail-badges">
            <Badge value={product.status} />
            {item.brandId === "kudu" ? <span className="status-pill" data-tone="info">KUDU anchor</span> : null}
          </div>
        </div>
      </div>

      <div className="mapping-detail-section">
        <h4>Description</h4>
        {product.descriptionEn || product.descriptionAr ? (
          <>
            {product.descriptionEn ? <p dir="auto">{product.descriptionEn}</p> : null}
            {product.descriptionAr ? <p dir="auto">{product.descriptionAr}</p> : null}
          </>
        ) : (
          <p className="meta-text">Not provided by source.</p>
        )}
      </div>

      <div className="mapping-detail-section">
        <h4>Pricing</h4>
        <div className="stack">
          <DetailRow label="Effective price">
            <Price value={effectivePrice} currency={product.currency} />
          </DetailRow>
          {product.regularPrice !== null ? (
            <DetailRow label="Regular price"><Price value={product.regularPrice} currency={product.currency} /></DetailRow>
          ) : null}
          {product.specialPrice !== null ? (
            <DetailRow label="Special price"><Price value={product.specialPrice} currency={product.currency} /></DetailRow>
          ) : null}
          {product.previousRegularPrice !== null ? (
            <DetailRow label="Previous regular"><Price value={product.previousRegularPrice} currency={product.currency} /></DetailRow>
          ) : null}
          {product.previousSpecialPrice !== null ? (
            <DetailRow label="Previous special"><Price value={product.previousSpecialPrice} currency={product.currency} /></DetailRow>
          ) : null}
          {comparison ? (
            <DetailRow label="Difference from KUDU">
              <span dir="ltr">{signedMoney(comparison.difference, product.currency)}</span>
              {comparison.percentage !== null ? <span dir="ltr"> · {signedPercent(comparison.percentage)}</span> : null}
              <span> · {comparisonCopy(comparison, product.currency)}</span>
            </DetailRow>
          ) : null}
        </div>
        <p className="mapping-price-note">
          The comparison uses the current base effective price. Size prices are shown as additional context only.
        </p>
      </div>

      {product.sizes.length > 0 ? (
        <div className="mapping-detail-section">
          <h4>Sizes</h4>
          <SizeList sizes={product.sizes} currency={product.currency} />
        </div>
      ) : null}

      <div className="mapping-detail-section">
        <h4>Product information</h4>
        <div className="stack">
          {product.category ? <DetailRow label="Category"><span dir="auto">{product.category}</span></DetailRow> : null}
          {product.categoryAr ? <DetailRow label="Category (Arabic)"><span dir="auto">{product.categoryAr}</span></DetailRow> : null}
          {product.calories !== null ? <DetailRow label="Calories">{product.calories}</DetailRow> : null}
          {product.availability !== null ? <DetailRow label="Available">{yesNo(product.availability)}</DetailRow> : null}
          {product.isPublished !== null ? <DetailRow label="Published">{yesNo(product.isPublished)}</DetailRow> : null}
          {product.isHidden !== null ? <DetailRow label="Hidden">{yesNo(product.isHidden)}</DetailRow> : null}
          <DetailRow label="Channel">{product.channel}</DetailRow>
          {product.location ? <DetailRow label="Location"><span dir="auto">{product.location}</span></DetailRow> : null}
          {product.firstSeenAt ? <DetailRow label="First seen">{formatRiyadhDateTime(product.firstSeenAt)}</DetailRow> : null}
          {product.lastSeenAt ? <DetailRow label="Last seen">{formatRiyadhDateTime(product.lastSeenAt)}</DetailRow> : null}
          {product.observedAt ? <DetailRow label="Observed">{formatRiyadhDateTime(product.observedAt)}</DetailRow> : null}
        </div>
      </div>
    </section>
  );
}
