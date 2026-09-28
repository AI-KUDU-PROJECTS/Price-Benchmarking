import { statusLabel, statusTone } from "../lib/status";

export function Badge({ value }: { value: string | null | undefined }) {
  const tone = statusTone(value);
  return (
    <span className="status-pill" data-tone={tone}>
      {statusLabel(value)}
    </span>
  );
}

export function EventType({ value }: { value: string | null | undefined }) {
  const tone = eventTone(value);
  return (
    <span className="event-type" data-tone={tone}>
      <span className="event-dot" aria-hidden="true" />
      {statusLabel(value)}
    </span>
  );
}

function eventTone(value: string | null | undefined): "success" | "error" | "warning" | "neutral" {
  if (!value) return "neutral";
  if (/(decreased|added|started|returned)/.test(value)) return "success";
  if (/(increased|removed|ended)/.test(value)) return "error";
  if (/not_observed/.test(value)) return "warning";
  return "neutral";
}
