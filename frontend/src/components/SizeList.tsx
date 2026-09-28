import type { ProductSize } from "../api/types";
import { Price } from "./Price";

export function SizeList({ sizes, currency }: { sizes: ProductSize[]; currency?: string | null }) {
  if (!sizes.length) return <span className="sizes">—</span>;
  return (
    <div className="sizes">
      {sizes.map((size) => (
        <div key={size.label}>
          {size.label}: <Price value={size.price} currency={size.currency || currency} />
        </div>
      ))}
    </div>
  );
}
