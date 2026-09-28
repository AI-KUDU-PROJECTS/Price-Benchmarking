export type Tone = "success" | "warning" | "error" | "info" | "neutral";

/**
 * Maps every status string used across brand health, collection runs, and
 * product/promotion lifecycles to one shared tone. Two different meanings
 * share the same words ("active", "partial") so this is a single explicit
 * table rather than a guess-by-regex - see the frontend rebuild report for
 * why each status landed where it did (e.g. "ended"/"removed" are informational
 * lifecycle states, not errors, so they read as neutral rather than red).
 */
const STATUS_TONE: Record<string, Tone> = {
  healthy: "success",
  success: "success",
  active: "success",
  returned: "success",
  new: "info",
  running: "info",
  pending: "neutral",
  partial: "warning",
  already_running: "warning",
  stale: "warning",
  not_observed: "warning",
  unpublished: "warning",
  removed: "neutral",
  ended: "neutral",
  disconnected: "neutral",
  unavailable: "neutral",
  error: "error",
  failed: "error",
};

export function statusTone(value: string | null | undefined): Tone {
  if (!value) return "neutral";
  return STATUS_TONE[value] ?? "neutral";
}

export function statusLabel(value: string | null | undefined): string {
  if (!value) return "Unknown";
  return value.replace(/_/g, " ");
}
