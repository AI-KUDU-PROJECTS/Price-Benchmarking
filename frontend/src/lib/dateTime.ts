export const RIYADH_TIME_ZONE = "Asia/Riyadh";
const formatter = new Intl.DateTimeFormat("en-US", {
  timeZone: RIYADH_TIME_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: true,
});

/**
 * Canonical user-facing timestamp: 2026-09-14 3:14 pm.
 * API timestamps are instants; older timezone-less values are treated as UTC.
 */
export function formatRiyadhDateTime(
  value: string | null | undefined,
  fallback = "—",
): string {
  if (!value) return fallback;

  const normalized = value.includes("T") ? value : value.replace(" ", "T");
  const hasOffset = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(normalized);
  const date = new Date(hasOffset ? normalized : `${normalized}Z`);
  if (Number.isNaN(date.getTime())) return value;

  const parts = Object.fromEntries(
    formatter.formatToParts(date).map(({ type, value: partValue }) => [type, partValue]),
  );
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute} ${parts.dayPeriod.toLowerCase()}`;
}
