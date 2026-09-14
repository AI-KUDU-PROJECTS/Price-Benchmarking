export function Price({
  value,
  currency,
  previous,
}: {
  value: number | null | undefined;
  currency?: string | null;
  previous?: number | null;
}) {
  if (value === null || value === undefined) {
    return <span className="price unknown" dir="ltr">—</span>;
  }
  const unit = currency || "SAR";
  return (
    <span className="price" dir="ltr">
      {previous !== null && previous !== undefined && previous !== value ? (
        <span className="price prev">
          {unit} {previous.toFixed(2)}
        </span>
      ) : null}
      {unit} {value.toFixed(2)}
    </span>
  );
}
