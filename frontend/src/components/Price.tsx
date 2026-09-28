import { ArrowDownRight, ArrowUpRight } from "lucide-react";

export function Price({
  value,
  currency,
  previous,
  showPreviousValue = true,
}: {
  value: number | null | undefined;
  currency?: string | null;
  previous?: number | null;
  /** Set to false when a separate column/element already shows the previous
   * price, so this only adds the direction arrow instead of repeating it. */
  showPreviousValue?: boolean;
}) {
  if (value === null || value === undefined) {
    return (
      <span className="price unknown" dir="ltr">
        —
      </span>
    );
  }
  const unit = currency || "SAR";
  const hasPrevious = previous !== null && previous !== undefined && previous !== value;
  const decreased = hasPrevious && (previous as number) > value;

  return (
    <span className="price" dir="ltr">
      {hasPrevious && showPreviousValue ? (
        <span className="price-previous">
          {unit} {(previous as number).toFixed(2)}
        </span>
      ) : null}
      <span>
        {unit} {value.toFixed(2)}
      </span>
      {hasPrevious ? (
        <span className={`price-delta ${decreased ? "down" : "up"}`}>
          {decreased ? (
            <ArrowDownRight size={14} aria-label="decreased from previous price" />
          ) : (
            <ArrowUpRight size={14} aria-label="increased from previous price" />
          )}
        </span>
      ) : null}
    </span>
  );
}
