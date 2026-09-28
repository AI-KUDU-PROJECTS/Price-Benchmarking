import type { ReactNode } from "react";

/** A single KPI tile. Deliberately a quiet subtle-surface block rather than
 * a bordered card, so a row of numbers doesn't read as five independent
 * content cards (see 03-product-patterns.md: avoid "four KPI cards" as
 * decoration - these numbers are the primary daily-check-in task here). */
export function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="kpi">
      <div className="kpi-value">{value}</div>
      <div className="kpi-label">{label}</div>
    </div>
  );
}
