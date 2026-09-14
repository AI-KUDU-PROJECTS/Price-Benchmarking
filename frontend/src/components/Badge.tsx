export function Badge({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="badge disconnected">Unknown</span>;
  const cls = value.replace(/-/g, "_");
  return <span className={`badge ${cls}`}>{value.replace(/_/g, " ")}</span>;
}

export function EventType({ value }: { value: string | null | undefined }) {
  const label = value ? value.replace(/_/g, " ") : "Unknown";
  const tone = eventTone(value);
  return <span className={`event-type${tone ? ` ${tone}` : ""}`}>{label}</span>;
}

function eventTone(value: string | null | undefined) {
  if (!value) return "";
  if (/(decreased|added|started|returned)/.test(value)) return "positive";
  if (/(increased|removed|ended)/.test(value)) return "negative";
  if (/not_observed/.test(value)) return "warning";
  return "";
}
