import { Search } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { DataTable } from "./DataTable";
import { ModalDialog } from "./ModalDialog";
import { ProductImage } from "./ProductImage";

export interface PlaygroundProductOption {
  brandId: string;
  brandName: string;
  productId: string;
  nameAr: string | null;
  nameEn: string | null;
  category: string | null;
  imageUrl: string | null;
  effectivePrice: number | null;
  currency: string | null;
  missing: boolean;
}

export function optionKey(option: Pick<PlaygroundProductOption, "brandId" | "productId">): string {
  return `${option.brandId}::${option.productId}`;
}

function optionName(option: PlaygroundProductOption): string {
  return option.nameEn || option.nameAr || option.productId;
}

export function ProductPickerDialog({
  open,
  title,
  description,
  options,
  selected,
  multiple,
  onApply,
  onRequestClose,
}: {
  open: boolean;
  title: string;
  description: string;
  options: PlaygroundProductOption[];
  selected: PlaygroundProductOption[];
  multiple: boolean;
  onApply: (products: PlaygroundProductOption[]) => void;
  onRequestClose: () => void;
}) {
  const searchId = useId();
  const brandFilterId = useId();
  const searchRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [brandId, setBrandId] = useState("");
  const [draftKeys, setDraftKeys] = useState<Set<string>>(new Set());

  const combinedOptions = useMemo(() => {
    const byKey = new Map<string, PlaygroundProductOption>();
    [...selected, ...options].forEach((option) => byKey.set(optionKey(option), option));
    return Array.from(byKey.values());
  }, [options, selected]);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setBrandId("");
    setDraftKeys(new Set(selected.map(optionKey)));
    const focusFrame = window.requestAnimationFrame(() => searchRef.current?.focus());
    return () => window.cancelAnimationFrame(focusFrame);
  }, [open, selected]);

  const brands = useMemo(() => {
    const values = new Map<string, string>();
    combinedOptions.forEach((option) => values.set(option.brandId, option.brandName));
    return Array.from(values, ([id, name]) => ({ id, name })).sort((a, b) => a.name.localeCompare(b.name));
  }, [combinedOptions]);

  const filtered = useMemo(() => {
    const term = query.trim().toLocaleLowerCase();
    return combinedOptions.filter((option) => {
      if (brandId && option.brandId !== brandId) return false;
      if (!term) return true;
      return [
        option.nameEn,
        option.nameAr,
        option.category,
        option.brandName,
      ].some((value) => value?.toLocaleLowerCase().includes(term));
    });
  }, [brandId, combinedOptions, query]);

  const apply = () => {
    const selectedOptions = combinedOptions.filter((option) => draftKeys.has(optionKey(option)));
    onApply(selectedOptions);
  };

  return (
    <ModalDialog
      open={open}
      title={title}
      description={description}
      onRequestClose={onRequestClose}
      footer={(
        <>
          <button type="button" className="btn btn-secondary" onClick={onRequestClose}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={apply}
            disabled={draftKeys.size === 0}
          >
            {multiple ? `Add ${draftKeys.size} selected` : "Use selected item"}
          </button>
        </>
      )}
    >
      <div className="picker-filters">
        <div className="form-field picker-search">
          <label htmlFor={searchId}>Search products</label>
          <div className="field-search">
            <Search size={16} aria-hidden="true" />
            <input
              ref={searchRef}
              id={searchId}
              className="control"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search product or category"
            />
          </div>
        </div>
        {multiple && brands.length > 1 ? (
          <div className="form-field">
            <label htmlFor={brandFilterId}>Competitor</label>
            <select
              id={brandFilterId}
              className="control"
              value={brandId}
              onChange={(event) => setBrandId(event.target.value)}
            >
              <option value="">All competitors</option>
              {brands.map((brand) => (
                <option key={brand.id} value={brand.id}>{brand.name}</option>
              ))}
            </select>
          </div>
        ) : null}
      </div>
      <p className="picker-result-count" aria-live="polite">
        {filtered.length} products · {draftKeys.size} selected
      </p>
      {filtered.length === 0 ? (
        <div className="picker-empty">No products match this search.</div>
      ) : (
        <div className="picker-table">
          <DataTable caption={title}>
            <thead>
              <tr>
                <th><span className="visually-hidden">Select</span></th>
                {multiple ? <th>Competitor</th> : null}
                <th><span className="visually-hidden">Image</span></th>
                <th>Product</th>
                <th>Category</th>
                <th className="num">Effective price</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((option) => {
                const key = optionKey(option);
                const checked = draftKeys.has(key);
                const unavailable = option.missing || option.effectivePrice === null || !option.currency;
                return (
                  <tr key={key}>
                    <td>
                      <input
                        type={multiple ? "checkbox" : "radio"}
                        name={multiple ? undefined : "playground-kudu-item"}
                        checked={checked}
                        disabled={unavailable && !checked}
                        aria-label={`Select ${optionName(option)}`}
                        onChange={() => {
                          if (multiple) {
                            setDraftKeys((current) => {
                              const next = new Set(current);
                              if (next.has(key)) next.delete(key);
                              else next.add(key);
                              return next;
                            });
                          } else {
                            setDraftKeys(new Set([key]));
                          }
                        }}
                      />
                    </td>
                    {multiple ? <td>{option.brandName}</td> : null}
                    <td><ProductImage src={option.imageUrl} alt={optionName(option)} /></td>
                    <td>
                      <span dir="auto">{optionName(option)}</span>
                      {option.nameAr && option.nameEn ? (
                        <div className="meta-text" dir="auto">{option.nameAr}</div>
                      ) : null}
                      {option.missing ? <div className="field-error">No longer available</div> : null}
                    </td>
                    <td>{option.category || "—"}</td>
                    <td className="num">
                      {unavailable ? "Unavailable" : `${option.currency} ${option.effectivePrice?.toFixed(2)}`}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </DataTable>
        </div>
      )}
    </ModalDialog>
  );
}

