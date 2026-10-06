import type { Dispatch, SetStateAction } from "react";
import type { Channel } from "../../api/types";
import { DataTable } from "../../components/DataTable";
import { Price } from "../../components/Price";
import { ProductImage } from "../../components/ProductImage";
import { optionKey, type PlaygroundProductOption } from "../../components/ProductPickerDialog";
import {
  channelLabel,
  comparePrices,
  flowProductName,
  signedMoney,
  signedPercent,
} from "../../lib/playground";

const CHANNELS: Array<{ value: Channel; label: string }> = [
  { value: "pickup", label: "Pickup" },
  { value: "delivery", label: "Delivery" },
  { value: "hungerstation", label: "HungerStation" },
];

type Props = {
  editing: boolean;
  formError: string | null;
  statusMessage: string | null;
  channel: Channel | "";
  catalogLoading: boolean;
  catalogError: string | null;
  kuduOptionCount: number;
  selectedKudu: PlaygroundProductOption | null;
  selectedCompetitors: PlaygroundProductOption[];
  mappingName: string;
  mappingIsComplete: boolean;
  saving: boolean;
  onChannelChange: (channel: Channel) => void;
  onOpenKuduPicker: () => void;
  onOpenCompetitorPicker: () => void;
  onCompetitorsChange: Dispatch<SetStateAction<PlaygroundProductOption[]>>;
  onMappingNameChange: (name: string) => void;
  onSave: () => void;
  onCancelEditing: () => void;
};

export function PlaygroundBuilder({
  editing,
  formError,
  statusMessage,
  channel,
  catalogLoading,
  catalogError,
  kuduOptionCount,
  selectedKudu,
  selectedCompetitors,
  mappingName,
  mappingIsComplete,
  saving,
  onChannelChange,
  onOpenKuduPicker,
  onOpenCompetitorPicker,
  onCompetitorsChange,
  onMappingNameChange,
  onSave,
  onCancelEditing,
}: Props) {
  return (
    <section className="playground-builder" aria-labelledby="playground-builder-title">
      <div className="section-heading">
        <div>
          <h2 id="playground-builder-title" className="section-title" tabIndex={-1}>
            {editing ? "Edit mapping" : "Build a comparison"}
          </h2>
          <p className="section-description">Complete the steps in order. Prices are never stored; the latest data is used each time.</p>
        </div>
        {editing ? <span className="status-pill" data-tone="info">Editing saved mapping</span> : null}
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
            onChange={(event) => onChannelChange(event.target.value as Channel)}
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
            <button type="button" className="btn btn-secondary" disabled={!channel || catalogLoading} onClick={onOpenKuduPicker}>
              {selectedKudu ? "Change KUDU item" : "Choose KUDU item"}
            </button>
          </div>
          {catalogLoading && channel ? <div className="inline-loading" role="status">Loading channel products.</div> : null}
          {catalogError ? <div className="field-error" role="alert">{catalogError}</div> : null}
          {!catalogLoading && channel && kuduOptionCount === 0 ? (
            <div className="inline-empty">No KUDU products are available for {channelLabel(channel)} yet.</div>
          ) : null}
          {selectedKudu ? (
            <div className="selected-product">
              <div className="selected-product-main">
                <ProductImage src={selectedKudu.imageUrl} alt={flowProductName(selectedKudu)} />
                <div>
                  <strong dir="auto">{flowProductName(selectedKudu)}</strong>
                  {selectedKudu.nameAr && selectedKudu.nameEn ? <div className="meta-text" dir="auto">{selectedKudu.nameAr}</div> : null}
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
            <button type="button" className="btn btn-secondary" disabled={!selectedKudu || catalogLoading} onClick={onOpenCompetitorPicker}>
              Add competitor items
            </button>
          </div>

          {selectedCompetitors.length === 0 ? (
            <div className="inline-empty">No competitor items selected.</div>
          ) : (
            <DataTable caption="Current price comparison">
              <thead>
                <tr>
                  <th>Competitor</th><th><span className="visually-hidden">Image</span></th><th>Product</th>
                  <th className="num">Effective price</th><th className="num">Difference</th>
                  <th className="num">Difference %</th><th>Position</th><th><span className="visually-hidden">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {selectedCompetitors.map((competitor) => {
                  const comparison = comparePrices(competitor, selectedKudu);
                  const positionLabel = comparison.position === "higher" ? "Higher"
                    : comparison.position === "lower" ? "Lower"
                      : comparison.position === "equal" ? "Equal" : "Unavailable";
                  return (
                    <tr key={optionKey(competitor)}>
                      <td>{competitor.brandName}</td>
                      <td><ProductImage src={competitor.imageUrl} alt={flowProductName(competitor)} /></td>
                      <td>
                        <span dir="auto">{flowProductName(competitor)}</span>
                        {competitor.nameAr && competitor.nameEn ? <div className="meta-text" dir="auto">{competitor.nameAr}</div> : null}
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
                          onClick={() => onCompetitorsChange((current) => current.filter((item) => optionKey(item) !== optionKey(competitor)))}
                        >Remove</button>
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
            <input id="playground-mapping-name" className="control" value={mappingName} maxLength={120} required
              disabled={selectedCompetitors.length === 0} onChange={(event) => onMappingNameChange(event.target.value)} />
          </div>
          <div className="action-row">
            <button type="button" className="btn btn-primary" disabled={!mappingIsComplete || saving} onClick={onSave}>
              {saving ? "Saving." : editing ? "Update mapping" : "Save mapping"}
            </button>
            {editing ? <button type="button" className="btn btn-secondary" onClick={onCancelEditing}>Cancel editing</button> : null}
          </div>
        </div>
      </div>
    </section>
  );
}
