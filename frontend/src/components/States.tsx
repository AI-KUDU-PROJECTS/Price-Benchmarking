import { AlertTriangle, Inbox } from "lucide-react";
import type { ReactNode } from "react";

type LoadingVariant = "table" | "cards" | "metrics" | "detail";

export function LoadingState({ variant = "table" }: { variant?: LoadingVariant }) {
  if (variant === "metrics") {
    return (
      <div className="skeleton">
        <div className="skeleton-grid metrics">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="skeleton-block skeleton-tile" />
          ))}
        </div>
      </div>
    );
  }
  if (variant === "cards") {
    return (
      <div className="skeleton">
        <div className="skeleton-grid cards">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="skeleton-block skeleton-card" />
          ))}
        </div>
      </div>
    );
  }
  if (variant === "detail") {
    return (
      <div className="skeleton">
        <div className="skeleton-block skeleton-row short" />
        <div className="skeleton-block skeleton-card" />
        <div className="skeleton-block skeleton-row" />
        <div className="skeleton-block skeleton-row" />
      </div>
    );
  }
  return (
    <div className="skeleton">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="skeleton-block skeleton-row" />
      ))}
    </div>
  );
}

export function EmptyState({ message, action }: { message: string; action?: ReactNode }) {
  return (
    <div className="state-block">
      <Inbox size={28} aria-hidden="true" />
      <p className="state-message">{message}</p>
      {action}
    </div>
  );
}

export function ErrorState({ error }: { error: Error }) {
  return (
    <div className="state-block error-state">
      <AlertTriangle size={28} aria-hidden="true" />
      <p className="state-title">Could not load this page</p>
      <p className="state-message">{error.message}</p>
      <button type="button" className="btn btn-secondary btn-sm" onClick={() => window.location.reload()}>
        Retry
      </button>
    </div>
  );
}
