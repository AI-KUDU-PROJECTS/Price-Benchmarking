import { Plus } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
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
import { PageHeader } from "../components/PageHeader";
import {
  ProductPickerDialog,
  optionKey,
  type PlaygroundProductOption,
} from "../components/ProductPickerDialog";
import { ErrorState, LoadingState } from "../components/States";
import { channelLabel, flowProductName } from "../lib/playground";
import { PlaygroundBuilder } from "./playground/PlaygroundBuilder";
import { SavedMappingsSection } from "./playground/SavedMappingsSection";

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

      <PlaygroundBuilder
        editing={Boolean(editingId)}
        formError={formError}
        statusMessage={statusMessage}
        channel={channel}
        catalogLoading={catalogLoading}
        catalogError={catalogError}
        kuduOptionCount={kuduOptions.length}
        selectedKudu={selectedKudu}
        selectedCompetitors={selectedCompetitors}
        mappingName={mappingName}
        mappingIsComplete={mappingIsComplete}
        saving={saving}
        onChannelChange={requestChannelChange}
        onOpenKuduPicker={() => setKuduPickerOpen(true)}
        onOpenCompetitorPicker={() => setCompetitorPickerOpen(true)}
        onCompetitorsChange={setSelectedCompetitors}
        onMappingNameChange={setMappingName}
        onSave={saveMapping}
        onCancelEditing={requestNewMapping}
      />

      <SavedMappingsSection
        mappings={mappings}
        onCreate={requestNewMapping}
        onEdit={(mapping) => {
          setAppliedEditId(mapping.id);
          setSearchParams({ edit: mapping.id }, { replace: true });
          openMapping(mapping);
        }}
        onDelete={(mapping) => setConfirmAction({ kind: "delete", mapping })}
      />

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
