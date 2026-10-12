import { ChevronLeft, ChevronRight } from "lucide-react";
import type { ListMeta } from "../api/types";

/** Quiet range + Previous/Next for server-paged lists. Renders nothing when
 * one page already holds every item, so short lists look unchanged. */
export function Pager({ meta, onPage }: { meta: ListMeta; onPage: (page: number) => void }) {
  if (meta.total <= meta.pageSize) return null;
  const lastPage = Math.ceil(meta.total / meta.pageSize);
  const first = Math.min((meta.page - 1) * meta.pageSize + 1, meta.total);
  const last = Math.min(meta.page * meta.pageSize, meta.total);

  function go(page: number) {
    onPage(page);
    window.scrollTo({ top: 0 });
  }

  return (
    <nav className="pager" aria-label="Pagination">
      <span className="meta-text">
        Showing {first}–{last} of {meta.total}
      </span>
      <div className="pager-actions">
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          disabled={meta.page <= 1}
          onClick={() => go(meta.page - 1)}
        >
          <ChevronLeft size={16} aria-hidden="true" />
          Previous
        </button>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          disabled={meta.page >= lastPage}
          onClick={() => go(meta.page + 1)}
        >
          Next
          <ChevronRight size={16} aria-hidden="true" />
        </button>
      </div>
    </nav>
  );
}
