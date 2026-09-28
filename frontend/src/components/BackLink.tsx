import { ArrowLeft } from "lucide-react";
import { Link } from "react-router-dom";

/** A quiet way back from a detail/drill-down page. Uses browser history when
 * there is somewhere to go back to, otherwise falls back to a known route
 * (e.g. a detail page opened directly from a bookmark or shared link). */
export function BackLink({ label, fallback }: { label: string; fallback: string }) {
  const hasHistory = window.history.length > 1;
  if (hasHistory) {
    return (
      <button type="button" className="back-link" onClick={() => window.history.back()}>
        <ArrowLeft size={16} aria-hidden="true" />
        {label}
      </button>
    );
  }
  return (
    <Link className="back-link" to={fallback}>
      <ArrowLeft size={16} aria-hidden="true" />
      {label}
    </Link>
  );
}
