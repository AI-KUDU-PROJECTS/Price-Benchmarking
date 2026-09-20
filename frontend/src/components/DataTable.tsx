import type { ReactNode } from "react";

/** Shared scroll/border treatment for every data table in the product, so a
 * page doesn't need to wrap its table in a card just to get a consistent
 * surface (D14: structured table; component spec: no default card shell). */
export function DataTable({ caption, children }: { caption?: string; children: ReactNode }) {
  return (
    <div className="table-surface">
      <div className="table-scroll">
        <table>
          {caption ? <caption className="visually-hidden">{caption}</caption> : null}
          {children}
        </table>
      </div>
    </div>
  );
}
