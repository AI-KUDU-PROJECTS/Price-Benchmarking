import { Trash2 } from "lucide-react";
import { Link } from "react-router-dom";
import type { PriceMapping } from "../../api/types";
import { DataTable } from "../../components/DataTable";
import { ProductImage } from "../../components/ProductImage";
import { EmptyState } from "../../components/States";
import { formatRiyadhDateTime } from "../../lib/dateTime";
import { channelLabel, flowProductName } from "../../lib/playground";

type Props = {
  mappings: PriceMapping[];
  onCreate: () => void;
  onEdit: (mapping: PriceMapping) => void;
  onDelete: (mapping: PriceMapping) => void;
};

export function SavedMappingsSection({ mappings, onCreate, onEdit, onDelete }: Props) {
  return (
    <section className="saved-mappings" aria-labelledby="saved-mappings-title">
      <div className="section-heading">
        <div>
          <h2 id="saved-mappings-title" className="section-title">Saved mappings</h2>
          <p className="section-description">Open a mapping flow to explore its nodes and latest product details.</p>
        </div>
        <span className="meta-text">{mappings.length} saved</span>
      </div>
      {mappings.length === 0 ? (
        <EmptyState message="No mappings have been saved yet."
          action={<button type="button" className="btn btn-primary" onClick={onCreate}>Create first mapping</button>} />
      ) : (
        <DataTable caption="Saved Playground mappings">
          <thead>
            <tr><th>Name</th><th>Channel</th><th>KUDU item</th><th className="num">Competitors</th><th>Updated</th><th>Actions</th></tr>
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
                    <Link className="btn btn-primary btn-sm" to={`/playground/mappings/${encodeURIComponent(mapping.id)}`}>View</Link>
                    <button type="button" className="btn btn-secondary btn-sm" onClick={() => onEdit(mapping)}>Edit</button>
                    <button type="button" className="btn btn-ghost btn-sm destructive-text" onClick={() => onDelete(mapping)}>
                      <Trash2 size={14} aria-hidden="true" /> Delete
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
    </section>
  );
}
