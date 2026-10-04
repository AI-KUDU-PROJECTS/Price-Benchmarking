import { Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type {
  Brand,
  Channel,
  MappingProduct,
  PriceMapping,
  PriceMappingWrite,
  Product,
} from "../api/types";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { DataTable } from "../components/DataTable";
import { PageHeader } from "../components/PageHeader";
import { Price } from "../components/Price";
import { ProductImage } from "../components/ProductImage";
import {
  ProductPickerDialog,
  optionKey,
  type PlaygroundProductOption,
} from "../components/ProductPickerDialog";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { formatRiyadhDateTime } from "../lib/dateTime";
import {
  channelLabel,
  comparePrices,
  flowProductName,
  signedMoney,
  signedPercent,
} from "../lib/playground";

const CHANNELS: Array<{ value: Channel; label: string }> = [
  { value: "pickup", label: "Pickup" },
  { value: "delivery", label: "Delivery" },
  { value: "hungerstation", label: "HungerStation" },
];

type ConfirmAction =
  | { kind: "delete"; mapping: PriceMapping }
  | { kind: "channel"; channel: Channel }
  | { kind: "kudu"; product: PlaygroundProductOption }
  | { kind: "new" };

function toOption(product: Product, brandName: string): PlaygroundProductOption {
  return {
    brandId: product.brandId,
    brandName,
    productId: product.id,
    nameAr: product.nameAr,
    nameEn: product.nameEn,
    category: product.category,
    imageUrl: product.imageUrl,
    effectivePrice: product.specialPrice ?? product.regularPrice,
    currency: product.currency,
    missing: false,
  };
}

function fromMappingProduct(product: MappingProduct): PlaygroundProductOption {
  return { ...product };
}

function readableError(error: unknown): string {
  if (error instanceof ApiError) {
    const body = error.body as { detail?: { message?: string } | string } | null;
    if (body?.detail && typeof body.detail === "object" && body.detail.message) {
      return body.detail.message;
    }
    if (typeof body?.detail === "string") return body.detail;
  }
  return error instanceof Error ? error.message : "Something went wrong.";
}

export function PlaygroundPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const editId = searchParams.get("edit");

  const [brands, setBrands] = useState<Brand[]>([]);
  const [mappings, setMappings] = useState<PriceMapping[]>([]);
  const [initialLoading, setInitialLoading] = useState(true);
  const [initialError, setInitialError] = useState<Error | null>(null);

  const [channel, setChannel] = useState<Channel | "">("");
  const [kuduOptions, setKuduOptions] = useState<PlaygroundProductOption[]>([]);
  const [competitorOptions, setCompetitorOptions] = useState<PlaygroundProductOption[]>([]);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogError, setCatalogError] = useState<string | null>(null);

  const [selectedKudu, setSelectedKudu] = useState<PlaygroundProductOption | null>(null);
  const [selectedCompetitors, setSelectedCompetitors] = useState<PlaygroundProductOption[]>([]);
  const [mappingName, setMappingName] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [appliedEditId, setAppliedEditId] = useState<string | null>(null);

  const [kuduPickerOpen, setKuduPickerOpen] = useState(false);
  const [competitorPickerOpen, setCompetitorPickerOpen] = useState(false);
  const [confirmAction, setConfirmAction] = useState<ConfirmAction | null>(null);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  const openMapping = useCallback((mapping: PriceMapping) => {
    const kudu = fromMappingProduct(mapping.kuduItem);
    setEditingId(mapping.id);
    setChannel(mapping.channel);
    setSelectedKudu(kudu);
    setSelectedCompetitors(mapping.competitorItems.map(fromMappingProduct));
    setMappingName(mapping.name);
    setFormError(null);
    setStatusMessage(null);
    requestAnimationFrame(() => {
      document.getElementById("playground-builder-title")?.focus();
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.brands(), api.playgroundMappings()])
      .then(([brandResponse, mappingResponse]) => {
        if (cancelled) return;
        setBrands(brandResponse.items);
        setMappings(mappingResponse.items);
        setInitialLoading(false);
      })
      .catch((error: Error) => {
        if (cancelled) return;
        setInitialError(error);
        setInitialLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!editId || initialLoading || appliedEditId === editId) return;
    setAppliedEditId(editId);
    const existing = mappings.find((mapping) => mapping.id === editId);
    if (existing) {
      openMapping(existing);
      return;
    }

    let cancelled = false;
    api.playgroundMapping(editId)
      .then((mapping) => {
        if (cancelled) return;
        setMappings((current) => [mapping, ...current.filter((item) => item.id !== mapping.id)]);
        openMapping(mapping);
      })
      .catch((error) => {
        if (!cancelled) setFormError(`Could not open this mapping. ${readableError(error)}`);
      });
    return () => {
      cancelled = true;
    };
  }, [appliedEditId, editId, initialLoading, mappings, openMapping]);

  useEffect(() => {
    if (!channel || brands.length === 0) {
      setKuduOptions([]);
      setCompetitorOptions([]);
      return;
    }

    let cancelled = false;
    setCatalogLoading(true);
    setCatalogError(null);
    const competitorBrands = brands.filter(
      (brand) => brand.id !== "kudu" && brand.channels.includes(channel),
    );
    const brandNames = new Map(brands.map((brand) => [brand.id, brand.name]));

    Promise.all([
      api.allProducts("kudu", channel),
      Promise.all(
        competitorBrands.map(async (brand) => ({
          brand,
          products: await api.allProducts(brand.id, channel),
        })),
      ),
    ])
      .then(([kuduProducts, competitorGroups]) => {
        if (cancelled) return;
        const nextKudu = kuduProducts.map((product) => toOption(product, "KUDU"));
        const nextCompetitors = competitorGroups.flatMap(({ brand, products }) =>
          products.map((product) => toOption(product, brand.name)),
        );
        setKuduOptions(nextKudu);
        setCompetitorOptions(nextCompetitors);
        const latest = new Map(
          [...nextKudu, ...nextCompetitors].map((option) => [optionKey(option), option]),
        );
        setSelectedKudu((current) => current ? latest.get(optionKey(current)) || current : null);
        setSelectedCompetitors((current) =>
          current.map((option) => latest.get(optionKey(option)) || option),
        );
        setCatalogLoading(false);
        if (!brandNames.has("kudu")) setCatalogError("KUDU data is not connected.");
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setCatalogError(readableError(error));
        setCatalogLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [brands, channel]);

  const mappingIsComplete = useMemo(() => {
    if (!channel || !mappingName.trim() || !selectedKudu || selectedKudu.missing) return false;
    if (selectedKudu.effectivePrice === null || !selectedKudu.currency) return false;
    if (selectedCompetitors.length === 0) return false;
    return selectedCompetitors.every(
      (item) => !item.missing
        && item.effectivePrice !== null
        && item.currency === selectedKudu.currency,
    );
  }, [channel, mappingName, selectedCompetitors, selectedKudu]);

  const clearEditQuery = () => {
    if (searchParams.has("edit")) setSearchParams({}, { replace: true });
  };

  const resetForm = () => {
    setChannel("");
    setSelectedKudu(null);
    setSelectedCompetitors([]);
    setMappingName("");
    setEditingId(null);
    setAppliedEditId(null);
    setFormError(null);
    setCatalogError(null);
    setStatusMessage(null);
    clearEditQuery();
  };

  const applyChannel = (nextChannel: Channel) => {
    setChannel(nextChannel);
    setSelectedKudu(null);
    setSelectedCompetitors([]);
    setMappingName("");
    setEditingId(null);
    setAppliedEditId(null);
    setFormError(null);
    setCatalogError(null);
    setStatusMessage(null);
    clearEditQuery();
  };

  const requestChannelChange = (nextChannel: Channel) => {
    if (nextChannel === channel) return;
    if (selectedKudu || selectedCompetitors.length > 0 || mappingName || editingId) {
      setConfirmAction({ kind: "channel", channel: nextChannel });
    } else {
      applyChannel(nextChannel);
    }
  };

  const applyKudu = (product: PlaygroundProductOption) => {
    setSelectedKudu(product);
    setSelectedCompetitors([]);
    if (!editingId || !mappingName.trim()) {
      setMappingName(`KUDU ${flowProductName(product)} · ${channelLabel(channel as Channel)}`);
    }
    setFormError(null);
    setStatusMessage(null);
  };

  const requestKuduChange = (products: PlaygroundProductOption[]) => {
    const next = products[0];
    setKuduPickerOpen(false);
    if (!next || optionKey(next) === (selectedKudu ? optionKey(selectedKudu) : "")) return;
    if (selectedCompetitors.length > 0) setConfirmAction({ kind: "kudu", product: next });
    else applyKudu(next);
  };

  const requestNewMapping = () => {
    if (selectedKudu || selectedCompetitors.length > 0 || mappingName || editingId) {
      setConfirmAction({ kind: "new" });
    } else {
      resetForm();
    }
  };

  const saveMapping = async () => {
    if (!channel || !selectedKudu || !mappingIsComplete) {
      setFormError("Complete the channel, KUDU item, mapping name, and competitor selections.");
      return;
    }
    const payload: PriceMappingWrite = {
      name: mappingName.trim(),
      channel,
      kuduProductId: selectedKudu.productId,
      competitorItems: selectedCompetitors.map((item) => ({
        brandId: item.brandId,
        productId: item.productId,
      })),
    };
    setSaving(true);
    setFormError(null);
    setStatusMessage(null);
    try {
      const saved = editingId
        ? await api.updatePlaygroundMapping(editingId, payload)
        : await api.createPlaygroundMapping(payload);
      navigate(`/playground/mappings/${encodeURIComponent(saved.id)}`);
    } catch (error) {
      setFormError(readableError(error));
    } finally {
      setSaving(false);
    }
  };

  const confirmCurrentAction = async () => {
    if (!confirmAction) return;
    if (confirmAction.kind === "channel") {
      applyChannel(confirmAction.channel);
      setConfirmAction(null);
      return;
    }
    if (confirmAction.kind === "kudu") {
      applyKudu(confirmAction.product);
      setConfirmAction(null);
      return;
    }
    if (confirmAction.kind === "new") {
      resetForm();
      setConfirmAction(null);
      return;
    }

    setDeleting(true);
    try {
      await api.deletePlaygroundMapping(confirmAction.mapping.id);
      setMappings((current) => current.filter((mapping) => mapping.id !== confirmAction.mapping.id));
      if (editingId === confirmAction.mapping.id) resetForm();
      setStatusMessage("Mapping deleted.");
      setConfirmAction(null);
    } catch (error) {
      setFormError(readableError(error));
      setConfirmAction(null);
    } finally {
      setDeleting(false);
    }
  };

  const confirmCopy = (() => {
    if (!confirmAction) return null;
    if (confirmAction.kind === "delete") {
      return {
        title: "Delete mapping?",
        message: `“${confirmAction.mapping.name}” will be permanently removed from this local system.`,
        label: "Delete mapping",
        destructive: true,
      };
    }
    if (confirmAction.kind === "channel") {
      return {
        title: "Change channel?",
        message: "Changing the channel clears the current KUDU item, competitor selections, and unsaved edits.",
        label: "Change channel",
        destructive: false,
      };
    }
    if (confirmAction.kind === "kudu") {
      return {
        title: "Change KUDU item?",
        message: "Changing the KUDU item clears the selected competitor items because their price differences will change.",
        label: "Change item",
        destructive: false,
      };
    }
    return {
      title: "Start a new mapping?",
      message: "The current unsaved selections will be cleared.",
      label: "Start new mapping",
      destructive: false,
    };
  })();

  if (initialLoading) return <LoadingState variant="detail" />;
  if (initialError) return <ErrorState error={initialError} />;

  return (
    <>
      <PageHeader
        title="Playground"
        subtitle="Map one KUDU item to selected competitor items and compare their latest effective prices."
        extra={(
          <button type="button" className="btn btn-secondary" onClick={requestNewMapping}>
            <Plus size={16} aria-hidden="true" />
            New mapping
          </button>
        )}
      />

      <section className="playground-builder" aria-labelledby="playground-builder-title">
        <div className="section-heading">
          <div>
            <h2 id="playground-builder-title" className="section-title" tabIndex={-1}>
              {editingId ? "Edit mapping" : "Build a comparison"}
            </h2>
            <p className="section-description">Complete the steps in order. Prices are never stored; the latest data is used each time.</p>
          </div>
          {editingId ? <span className="status-pill" data-tone="info">Editing saved mapping</span> : null}
        </div>

        {formError ? (
          <div className="alert" data-tone="error" role="alert">
            <div className="alert-text"><strong>Could not save changes.</strong> {formError}</div>
          </div>
        ) : null}
        {statusMessage ? (
          <div className="alert" data-tone="success" role="status">
            <div className="alert-text">{statusMessage}</div>
          </div>
        ) : null}

        <div className="workflow-step">
          <div className="workflow-number" aria-hidden="true">1</div>
          <div className="workflow-content">
            <label className="step-title" htmlFor="playground-channel">Choose channel <span aria-hidden="true">*</span></label>
            <p className="step-help">KUDU and competitor items must come from the same channel.</p>
            <select
              id="playground-channel"
              className="control playground-channel"
              value={channel}
              required
              onChange={(event) => requestChannelChange(event.target.value as Channel)}
            >
              <option value="" disabled>Select channel</option>
              {CHANNELS.map((item) => (
                <option key={item.value} value={item.value}>{item.label}</option>
              ))}
            </select>
          </div>
        </div>

        <div className={`workflow-step${channel ? "" : " disabled-step"}`}>
          <div className="workflow-number" aria-hidden="true">2</div>
          <div className="workflow-content">
            <div className="step-action-heading">
              <div>
                <h3 className="step-title">Choose KUDU item <span aria-hidden="true">*</span></h3>
                <p className="step-help">Select the KUDU item that anchors this comparison.</p>
              </div>
              <button
                type="button"
                className="btn btn-secondary"
                disabled={!channel || catalogLoading}
                onClick={() => setKuduPickerOpen(true)}
              >
                {selectedKudu ? "Change KUDU item" : "Choose KUDU item"}
              </button>
            </div>
            {catalogLoading && channel ? <div className="inline-loading" role="status">Loading channel products…</div> : null}
            {catalogError ? <div className="field-error" role="alert">{catalogError}</div> : null}
            {!catalogLoading && channel && kuduOptions.length === 0 ? (
              <div className="inline-empty">No KUDU products are available for {channelLabel(channel)} yet.</div>
            ) : null}
            {selectedKudu ? (
              <div className="selected-product">
                <div className="selected-product-main">
                  <ProductImage src={selectedKudu.imageUrl} alt={flowProductName(selectedKudu)} />
                  <div>
                    <strong dir="auto">{flowProductName(selectedKudu)}</strong>
                    {selectedKudu.nameAr && selectedKudu.nameEn ? (
                      <div className="meta-text" dir="auto">{selectedKudu.nameAr}</div>
                    ) : null}
                    <div className="meta-text">{selectedKudu.category || "Category unavailable"}</div>
                  </div>
                </div>
                <div>
                  <Price value={selectedKudu.effectivePrice} currency={selectedKudu.currency} />
                  {selectedKudu.missing ? <div className="field-error">No longer available</div> : null}
                </div>
              </div>
            ) : null}
          </div>
        </div>

        <div className={`workflow-step${selectedKudu ? "" : " disabled-step"}`}>
          <div className="workflow-number" aria-hidden="true">3</div>
          <div className="workflow-content">
            <div className="step-action-heading">
              <div>
                <h3 className="step-title">Choose competitor items <span aria-hidden="true">*</span></h3>
                <p className="step-help">Choose any number of items from any available competitors.</p>
              </div>
              <button
                type="button"
                className="btn btn-secondary"
                disabled={!selectedKudu || catalogLoading}
                onClick={() => setCompetitorPickerOpen(true)}
              >
                Add competitor items
              </button>
            </div>

            {selectedCompetitors.length === 0 ? (
              <div className="inline-empty">No competitor items selected.</div>
            ) : (
              <DataTable caption="Current price comparison">
                <thead>
                  <tr>
                    <th>Competitor</th>
                    <th><span className="visually-hidden">Image</span></th>
                    <th>Product</th>
                    <th className="num">Effective price</th>
                    <th className="num">Difference</th>
                    <th className="num">Difference %</th>
                    <th>Position</th>
                    <th><span className="visually-hidden">Actions</span></th>
                  </tr>
                </thead>
                <tbody>
                  {selectedCompetitors.map((competitor) => {
                    const comparison = comparePrices(competitor, selectedKudu);
                    const positionLabel = comparison.position === "higher"
                      ? "Higher"
                      : comparison.position === "lower"
                        ? "Lower"
                        : comparison.position === "equal"
                          ? "Equal"
                          : "Unavailable";
                    return (
                      <tr key={optionKey(competitor)}>
                        <td>{competitor.brandName}</td>
                        <td><ProductImage src={competitor.imageUrl} alt={flowProductName(competitor)} /></td>
                        <td>
                          <span dir="auto">{flowProductName(competitor)}</span>
                          {competitor.nameAr && competitor.nameEn ? (
                            <div className="meta-text" dir="auto">{competitor.nameAr}</div>
                          ) : null}
                          {competitor.missing ? <div className="field-error">No longer available</div> : null}
                        </td>
                        <td className="num"><Price value={competitor.effectivePrice} currency={competitor.currency} /></td>
                        <td className="num" dir="ltr">{signedMoney(comparison.difference, competitor.currency)}</td>
                        <td className="num" dir="ltr">{signedPercent(comparison.percentage)}</td>
                        <td><span className="status-pill" data-tone="neutral">{positionLabel}</span></td>
                        <td>
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm"
                            aria-label={`Remove ${flowProductName(competitor)}`}
                            onClick={() => setSelectedCompetitors((current) =>
                              current.filter((item) => optionKey(item) !== optionKey(competitor)),
                            )}
                          >
                            Remove
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </DataTable>
            )}
          </div>
        </div>

        <div className={`workflow-step${selectedCompetitors.length > 0 ? "" : " disabled-step"}`}>
          <div className="workflow-number" aria-hidden="true">4</div>
          <div className="workflow-content">
            <h3 className="step-title">Name and save mapping <span aria-hidden="true">*</span></h3>
            <p className="step-help">The suggested name is editable. Multiple mappings may use the same KUDU item.</p>
            <div className="form-field mapping-name-field">
              <label htmlFor="playground-mapping-name">Mapping name <span aria-hidden="true">*</span></label>
              <input
                id="playground-mapping-name"
                className="control"
                value={mappingName}
                maxLength={120}
                required
                disabled={selectedCompetitors.length === 0}
                onChange={(event) => setMappingName(event.target.value)}
              />
            </div>
            <div className="action-row">
              <button
                type="button"
                className="btn btn-primary"
                disabled={!mappingIsComplete || saving}
                onClick={saveMapping}
              >
                {saving ? "Saving…" : editingId ? "Update mapping" : "Save mapping"}
              </button>
              {editingId ? (
                <button type="button" className="btn btn-secondary" onClick={requestNewMapping}>
                  Cancel editing
                </button>
              ) : null}
            </div>
          </div>
        </div>
      </section>

      <section className="saved-mappings" aria-labelledby="saved-mappings-title">
        <div className="section-heading">
          <div>
            <h2 id="saved-mappings-title" className="section-title">Saved mappings</h2>
            <p className="section-description">Open a mapping flow to explore its nodes and latest product details.</p>
          </div>
          <span className="meta-text">{mappings.length} saved</span>
        </div>
        {mappings.length === 0 ? (
          <EmptyState
            message="No mappings have been saved yet."
            action={<button type="button" className="btn btn-primary" onClick={requestNewMapping}>Create first mapping</button>}
          />
        ) : (
          <DataTable caption="Saved Playground mappings">
            <thead>
              <tr>
                <th>Name</th>
                <th>Channel</th>
                <th>KUDU item</th>
                <th className="num">Competitors</th>
                <th>Updated</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {mappings.map((mapping) => (
                <tr key={mapping.id}>
                  <td><strong dir="auto">{mapping.name}</strong></td>
                  <td>{channelLabel(mapping.channel)}</td>
                  <td>
                    <div className="product-with-image">
                      <ProductImage src={mapping.kuduItem.imageUrl} alt={flowProductName(mapping.kuduItem)} />
                      <div>
                        <span dir="auto">{flowProductName(mapping.kuduItem)}</span>
                        {mapping.kuduItem.missing ? <div className="field-error">No longer available</div> : null}
                      </div>
                    </div>
                  </td>
                  <td className="num">{mapping.competitorItems.length}</td>
                  <td className="nowrap">{formatRiyadhDateTime(mapping.updatedAt)}</td>
                  <td>
                    <div className="row-actions">
                      <Link className="btn btn-primary btn-sm" to={`/playground/mappings/${encodeURIComponent(mapping.id)}`}>
                        View
                      </Link>
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        onClick={() => {
                          setAppliedEditId(mapping.id);
                          setSearchParams({ edit: mapping.id }, { replace: true });
                          openMapping(mapping);
                        }}
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm destructive-text"
                        onClick={() => setConfirmAction({ kind: "delete", mapping })}
                      >
                        <Trash2 size={14} aria-hidden="true" />
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        )}
      </section>

      <ProductPickerDialog
        open={kuduPickerOpen}
        title="Choose KUDU item"
        description={channel ? `Showing KUDU products from ${channelLabel(channel)}.` : "Choose a channel first."}
        options={kuduOptions}
        selected={selectedKudu ? [selectedKudu] : []}
        multiple={false}
        onApply={requestKuduChange}
        onRequestClose={() => setKuduPickerOpen(false)}
      />
      <ProductPickerDialog
        open={competitorPickerOpen}
        title="Choose competitor items"
        description={channel ? `Select any items available in ${channelLabel(channel)}.` : "Choose a channel first."}
        options={competitorOptions}
        selected={selectedCompetitors}
        multiple
        onApply={(products) => {
          setSelectedCompetitors(products);
          setCompetitorPickerOpen(false);
          setFormError(null);
          setStatusMessage(null);
        }}
        onRequestClose={() => setCompetitorPickerOpen(false)}
      />
      {confirmCopy ? (
        <ConfirmDialog
          open={Boolean(confirmAction)}
          title={confirmCopy.title}
          message={confirmCopy.message}
          confirmLabel={confirmCopy.label}
          destructive={confirmCopy.destructive}
          busy={deleting}
          onConfirm={confirmCurrentAction}
          onRequestClose={() => setConfirmAction(null)}
        />
      ) : null}
    </>
  );
}
