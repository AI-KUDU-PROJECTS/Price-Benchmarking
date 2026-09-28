import { AlertTriangle, Clock, WifiOff } from "lucide-react";
import type { ReactNode } from "react";
import type { Freshness, Health } from "../api/types";
import { formatRiyadhDateTime } from "../lib/dateTime";
import type { Tone } from "../lib/status";

function Alert({
  tone,
  icon,
  children,
}: {
  tone: Tone;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="alert" data-tone={tone} role="status">
      <span className="alert-icon">{icon}</span>
      <p className="alert-text">{children}</p>
    </div>
  );
}

export function DataBanner({
  freshness,
  health,
  lastUpdatedAt,
}: {
  freshness?: Freshness;
  health?: Health;
  lastUpdatedAt?: string | null;
}) {
  const lastUpdated = formatRiyadhDateTime(lastUpdatedAt, "never");

  if (health === "disconnected") {
    return (
      <Alert tone="neutral" icon={<WifiOff size={18} aria-hidden="true" />}>
        This brand is not connected yet.
      </Alert>
    );
  }
  if (health === "error" || freshness === "unavailable") {
    return (
      <Alert tone="error" icon={<AlertTriangle size={18} aria-hidden="true" />}>
        No successful collection is available. Last update: <strong>{lastUpdated}</strong>.
      </Alert>
    );
  }
  if (health === "partial") {
    return (
      <Alert tone="warning" icon={<Clock size={18} aria-hidden="true" />}>
        Partial data: one channel failed or is incomplete. Last successful update{" "}
        <strong>{formatRiyadhDateTime(lastUpdatedAt, "unknown")}</strong>.
      </Alert>
    );
  }
  if (freshness === "stale" || health === "stale") {
    return (
      <Alert tone="warning" icon={<Clock size={18} aria-hidden="true" />}>
        Data is stale. Last successful update{" "}
        <strong>{formatRiyadhDateTime(lastUpdatedAt, "unknown")}</strong> Riyadh time. This page is
        not fully current.
      </Alert>
    );
  }
  return null;
}
