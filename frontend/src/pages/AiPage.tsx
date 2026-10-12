import { useEffect, useState } from "react";
import { Bot } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { AiMatch, AiSuggestion, Channel, Product } from "../api/types";
import { useApi } from "../api/useApi";
import { DataTable } from "../components/DataTable";
import { PageHeader } from "../components/PageHeader";
import { Price } from "../components/Price";
import { ProductImage } from "../components/ProductImage";
import { ProductPickerDialog, type PlaygroundProductOption } from "../components/ProductPickerDialog";
import { ErrorState, LoadingState } from "../components/States";
import { channelLabel } from "../lib/playground";
import { setSearchParam } from "../lib/params";

const CHANNELS: Channel[] = ["hungerstation", "delivery", "pickup"];

const CONFIDENCE_TONE: Record<AiMatch["confidence"], string> = {
  high: "success",
  medium: "warning",
  none: "neutral",
};

type Choice = "suggested" | "alternative" | "skip";

function effectivePrice(product: Product | null): number | null {
  return product ? product.specialPrice ?? product.regularPrice : null;
}

function toOption(product: Product): PlaygroundProductOption {
  return {
    brandId: product.brandId,
    brandName: "KUDU",
    productId: product.id,
    nameAr: product.nameAr,
    nameEn: product.nameEn,
    category: product.category,
    imageUrl: product.imageUrl,
    effectivePrice: effectivePrice(product),
    currency: product.currency,
    missing: false,
  };
}

function errorMessage(reason: unknown): string {
  if (reason instanceof ApiError) {
    const detail = (reason.body as { detail?: { message?: string } } | null)?.detail;
    if (detail?.message) return detail.message;
  }
  return reason instanceof Error ? reason.message : "The request failed.";
}

function difference(price: number | null, kuduPrice: number | null): string {
  if (price === null || kuduPrice === null || kuduPrice === 0) return "—";
  const amount = price - kuduPrice;
  const percent = (amount / kuduPrice) * 100;
  const sign = amount > 0 ? "+" : "";
  return `${sign}${amount.toFixed(2)} (${sign}${percent.toFixed(0)}%)`;
}

export function AiPage() {
  const [params, setParams] = useSearchParams();
  const channel = (params.get("channel") || "hungerstation") as Channel;
  const [statusKey, setStatusKey] = useState(0);
  const status = useApi(() => api.aiStatus(), [statusKey], { keepPreviousData: true });
  const kuduProducts = useApi(() => api.allProducts("kudu", channel), [channel]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [kudu, setKudu] = useState<PlaygroundProductOption | null>(null);
  const [suggestion, setSuggestion] = useState<AiSuggestion | null>(null);
  const [choices, setChoices] = useState<Record<string, Choice>>({});
  const [mappingName, setMappingName] = useState("");
  const [running, setRunning] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedId, setSavedId] = useState<string | null>(null);

  // A new channel means a different KUDU menu: start over.
  useEffect(() => {
    setKudu(null);
    setSuggestion(null);
    setSavedId(null);
    setError(null);
  }, [channel]);

  function chooseKudu(products: PlaygroundProductOption[]) {
    setPickerOpen(false);
    const next = products[0];
    if (!next) return;
    setKudu(next);
    setSuggestion(null);
    setSavedId(null);
    setError(null);
    setMappingName(`KUDU ${next.nameEn || next.nameAr || next.productId} · ${channelLabel(channel)}`);
  }

  async function suggest() {
    if (!kudu) return;
    setRunning(true);
    setError(null);
    setSavedId(null);
    try {
      const result = await api.suggestAiMapping(kudu.productId, channel);
      setSuggestion(result);
      setChoices(Object.fromEntries(result.matches.map((match) => [
        match.brandId,
        match.product && match.confidence !== "none" ? "suggested" : "skip",
      ])));
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setRunning(false);
      setStatusKey((value) => value + 1);
    }
  }

  function chosenProduct(match: AiMatch): Product | null {
    const choice = choices[match.brandId];
    if (choice === "suggested") return match.product;
    if (choice === "alternative") return match.alternative;
    return null;
  }

  const selected = suggestion
    ? suggestion.matches.flatMap((match) => {
      const product = chosenProduct(match);
      return product ? [{ brandId: match.brandId, productId: product.id }] : [];
    })
    : [];

  async function save() {
    if (!kudu || selected.length === 0 || !mappingName.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const mapping = await api.createPlaygroundMapping({
        name: mappingName.trim(),
        channel,
        kuduProductId: kudu.productId,
        competitorItems: selected,
      });
      setSavedId(mapping.id);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setSaving(false);
    }
  }

  if (status.loading && !status.data) return <LoadingState variant="metrics" />;
  if (status.error) return <ErrorState error={status.error} />;
  const summary = status.data;
  const kuduPrice = suggestion ? effectivePrice(suggestion.kuduProduct) : null;

  return (
    <>
      <PageHeader
        title="AI"
        subtitle="Choose a KUDU item and the AI suggests the matching item at each competitor. Review it, then save it as a Playground mapping."
      />
      {summary && !summary.configured ? (
        <div className="alert" data-tone="error" role="alert">
          <p className="alert-text">AI is not configured on this server: set ANTHROPIC_API_KEY in .env and restart the app.</p>
        </div>
      ) : null}

      <section className="card ai-panel" aria-labelledby="ai-step-1">
        <h2 id="ai-step-1" className="panel-title">1. Choose the KUDU item</h2>
        <div className="filter-bar">
          <label className="visually-hidden" htmlFor="ai-channel">Channel</label>
          <select id="ai-channel" className="control" value={channel} onChange={(event) => setSearchParam(setParams, params, "channel", event.target.value)}>
            {CHANNELS.map((value) => <option key={value} value={value}>{channelLabel(value)}</option>)}
          </select>
          <button type="button" className="btn btn-secondary" onClick={() => setPickerOpen(true)} disabled={!kuduProducts.data}>
            {kudu ? "Change KUDU item" : "Choose KUDU item"}
          </button>
          {kudu ? (
            <span className="product-with-image ai-image ai-image-kudu">
              <ProductImage src={kudu.imageUrl} alt={kudu.nameEn || ""} />
              <span>
                <strong>{kudu.nameEn || kudu.nameAr}</strong>{" "}
                <Price value={kudu.effectivePrice} currency={kudu.currency} />
              </span>
            </span>
          ) : null}
        </div>
        {kuduProducts.error ? <ErrorState error={kuduProducts.error} /> : null}
      </section>

      <section className="card ai-panel" aria-labelledby="ai-step-2">
        <h2 id="ai-step-2" className="panel-title">2. Get AI suggestions</h2>
        <div className="filter-bar">
          <button
            type="button"
            className="btn btn-primary"
            onClick={suggest}
            disabled={!kudu || running || !summary?.configured}
            aria-busy={running}
          >
            <Bot size={16} aria-hidden="true" />
            {running ? "AI is matching… (about 20–40 seconds)" : "Suggest matches"}
          </button>
          {suggestion ? (
            <span className="meta-text">Done in {suggestion.seconds}s · ≈ ${suggestion.costUsd.toFixed(2)}</span>
          ) : null}
        </div>
        {error ? <div className="alert" data-tone="error" role="alert"><p className="alert-text">{error}</p></div> : null}
      </section>

      {suggestion ? (
        <section className="card ai-panel" aria-labelledby="ai-step-3">
          <h2 id="ai-step-3" className="panel-title">3. Review and save</h2>
          <DataTable caption="AI suggested competitor items">
            <thead>
              <tr>
                <th>Brand</th>
                <th>Use</th>
                <th><span className="visually-hidden">Image</span></th>
                <th>Item</th>
                <th className="num">Price</th>
                <th className="num">vs KUDU</th>
                <th>Confidence</th>
                <th>Why</th>
                <th>Differences</th>
              </tr>
            </thead>
            <tbody>
              {suggestion.matches.map((match) => {
                const product = chosenProduct(match);
                const price = effectivePrice(product);
                return (
                  <tr key={match.brandId}>
                    <td className="nowrap"><strong>{match.brandName}</strong></td>
                    <td>
                      <label className="visually-hidden" htmlFor={`ai-use-${match.brandId}`}>Use for {match.brandName}</label>
                      <select
                        id={`ai-use-${match.brandId}`}
                        className="control ai-use"
                        value={choices[match.brandId] ?? "skip"}
                        onChange={(event) => setChoices({ ...choices, [match.brandId]: event.target.value as Choice })}
                      >
                        {match.product ? <option value="suggested">Suggested</option> : null}
                        {match.alternative ? <option value="alternative">Alternative: {match.alternative.nameEn || match.alternative.nameAr}</option> : null}
                        <option value="skip">Don't include</option>
                      </select>
                    </td>
                    <td className="ai-image"><ProductImage src={product?.imageUrl ?? null} alt={product?.nameEn || ""} /></td>
                    <td>{product ? product.nameEn || product.nameAr : <span className="meta-text">No item</span>}</td>
                    <td className="num"><Price value={price} currency={product?.currency} /></td>
                    <td className="num nowrap">{difference(price, kuduPrice)}</td>
                    <td><span className="status-pill" data-tone={CONFIDENCE_TONE[match.confidence]}>{match.confidence}</span></td>
                    <td className="ai-why">{match.reason}</td>
                    <td className="ai-why">{match.differences || "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </DataTable>
          <div className="filter-bar" style={{ marginTop: 16 }}>
            <label className="visually-hidden" htmlFor="ai-mapping-name">Mapping name</label>
            <input
              id="ai-mapping-name"
              className="control"
              style={{ minWidth: "22rem" }}
              value={mappingName}
              onChange={(event) => setMappingName(event.target.value)}
              placeholder="Mapping name"
            />
            <button
              type="button"
              className="btn btn-primary"
              onClick={save}
              disabled={saving || selected.length === 0 || !mappingName.trim() || Boolean(savedId)}
            >
              {saving ? "Saving…" : `Save mapping (${selected.length} competitors)`}
            </button>
          </div>
          {savedId ? (
            <div className="alert" data-tone="success" role="status">
              <p className="alert-text">
                Saved. <Link className="linkish" to={`/playground/mappings/${encodeURIComponent(savedId)}`}>Open the mapping</Link> or find it in the Playground.
              </p>
            </div>
          ) : null}
        </section>
      ) : null}

      <ProductPickerDialog
        open={pickerOpen}
        title="Choose KUDU item"
        description={`Showing KUDU products from ${channelLabel(channel)}.`}
        options={(kuduProducts.data ?? []).map(toOption)}
        selected={kudu ? [kudu] : []}
        multiple={false}
        onApply={chooseKudu}
        onRequestClose={() => setPickerOpen(false)}
      />
    </>
  );
}
