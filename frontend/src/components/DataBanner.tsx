import type { Freshness, Health } from "../api/types";

export function DataBanner({
  freshness,
  health,
  lastUpdatedAt,
}: {
  freshness?: Freshness;
  health?: Health;
  lastUpdatedAt?: string | null;
}) {
  if (health === "disconnected") {
    return (
      <div className="banner disconnected">
        This competitor is not connected yet. The first slice covers KFC only.
      </div>
    );
  }
  if (health === "error" || freshness === "unavailable") {
    return (
      <div className="banner error">
        No successful collection is available. Last update: {lastUpdatedAt || "never"}.
      </div>
    );
  }
  if (health === "partial") {
    return (
      <div className="banner stale">
        Partial data: one channel failed or is incomplete. Last successful update {lastUpdatedAt || "unknown"}.
      </div>
    );
  }
  if (freshness === "stale" || health === "stale") {
    return (
      <div className="banner stale">
        Data is stale. Last successful update {lastUpdatedAt || "unknown"} (Asia/Riyadh). This page is not fully current.
      </div>
    );
  }
  return null;
}
