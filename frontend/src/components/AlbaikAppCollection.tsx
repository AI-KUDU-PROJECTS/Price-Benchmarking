import { useEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import { api } from "../api/client";
import type { PullRun } from "../api/types";
import { formatRiyadhDateTime } from "../lib/dateTime";
import { Badge } from "./Badge";
import { DataTable } from "./DataTable";

export function useAlbaikAppCollection(onComplete: () => void) {
  const [run, setRun] = useState<PullRun | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const complete = useRef(onComplete);
  const previous = useRef<PullRun | null>(null);
  complete.current = onComplete;

  useEffect(() => {
    let active = true;
    let busy = false;
    async function update() {
      if (busy) return;
      busy = true;
      try {
        const response = await api.albaikAppPullStatus();
        if (!active) return;
        if (previous.current && response.run && response.run.status !== "running" &&
          (previous.current.status === "running" || previous.current.runId !== response.run.runId)) complete.current();
        previous.current = response.run;
        setRun(response.run);
        setError(null);
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "Could not load collection status.");
      } finally { busy = false; }
    }
    void update();
    // Keep observing idle runs too, so a scheduled collection appears without a reload.
    const timer = window.setInterval(update, 3000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  async function start() {
    setStarting(true);
    setError(null);
    try {
      const next = (await api.startAlbaikAppPull()).run;
      previous.current = next;
      setRun(next);
    }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Could not start AlBaik collection."); }
    finally { setStarting(false); }
  }

  return { run, starting, error, start };
}

type CollectionState = ReturnType<typeof useAlbaikAppCollection>;

export function AlbaikAppCollectionButton({ collection }: { collection: CollectionState }) {
  return (
    <button type="button" className="btn btn-secondary" onClick={collection.start} disabled={collection.starting || collection.run?.status === "running"}>
      <RefreshCw size={18} aria-hidden="true" /> Collect Albaik app
    </button>
  );
}

export function AlbaikAppCollection({ collection }: { collection: CollectionState }) {
  const { run, error } = collection;
  return (
    <section className="pull-panel" aria-label="Albaik App Collection">
      <div className="pull-panel-heading">
        <h2 className="panel-title">Albaik App Collection</h2>
        {run && <span aria-live="polite"><Badge value={run.status} /></span>}
      </div>
      {error && <div className="alert" data-tone="error" role="alert"><p className="alert-text">{error}</p></div>}
      {run ? <>
        <p className="meta-text">{run.trigger === "scheduled" ? "Automatic run · " : ""}Started {formatRiyadhDateTime(run.startedAt)} · Finished {formatRiyadhDateTime(run.completedAt)}</p>
        <DataTable caption="AlBaik app collection status by channel">
          <thead><tr><th>Channel</th><th>Status</th><th>Started</th><th>Finished</th><th>Result / failure reason</th></tr></thead>
          <tbody>{run.brands.map((row) => <tr key={row.id}>
            <td>{row.name}</td><td><Badge value={row.status} /></td>
            <td className="nowrap">{formatRiyadhDateTime(row.startedAt)}</td>
            <td className="nowrap">{formatRiyadhDateTime(row.completedAt)}</td>
            <td className="collection-result" aria-live="polite">{row.message || "—"}</td>
          </tr>)}</tbody>
        </DataTable>
      </> : <p className="meta-text">No app collection yet. Start a collection to check pickup and delivery.</p>}
    </section>
  );
}
