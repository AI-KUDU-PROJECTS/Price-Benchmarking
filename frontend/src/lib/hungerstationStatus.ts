import type { CollectionRun, PullRun } from "../api/types";

/** Include a newer successful KUDU menu without rewriting the scheduled run. */
export function withLatestKuduResult(batch: PullRun, runs: CollectionRun[]): PullRun {
  const kudu = batch.brands.find((brand) => brand.id === "kudu");
  if (!kudu || kudu.status === "pending" || kudu.status === "running") return batch;
  const boundary = Date.parse(kudu.completedAt || kudu.startedAt || batch.startedAt);
  const latest = runs
    .filter((run) => run.brandId === "kudu" && run.channel === "hungerstation"
      && run.status === "success" && run.completedAt && run.startedAt
      && Date.parse(run.startedAt) > boundary && (run.itemCount ?? 0) > 0)
    .sort((a, b) => Date.parse(b.completedAt!) - Date.parse(a.completedAt!))[0];
  if (!latest) return batch;

  const brands = batch.brands.map((brand) => brand.id !== "kudu" ? brand : {
    ...brand, status: "success" as const,
    startedAt: latest.startedAt, completedAt: latest.completedAt,
    message: `Collected ${latest.itemCount} products from HungerStation. Updated by a newer collection.`,
  });
  // Other restaurants may still be collecting; keep their progress and run identity.
  if (batch.status === "running") return { ...batch, brands };
  const status = brands.every((brand) => brand.status === "success") ? "success"
    : brands.some((brand) => brand.status === "success" || brand.status === "partial") ? "partial" : "failed";
  const completedAt = [batch.completedAt, latest.completedAt]
    .filter((value): value is string => value !== null)
    .sort((a, b) => Date.parse(b) - Date.parse(a))[0];
  return {
    ...batch, brands, status, completedAt, view: "latest_results",
    runId: `${batch.runId}:${latest.id}`, trigger: undefined,
  };
}
