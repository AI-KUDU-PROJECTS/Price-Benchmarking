import { Search } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";

const SEARCH_DEBOUNCE_MS = 300;

/** Labeled search input that keeps the URL-backed query in sync. Search can
 * be submitted by typing, pressing Enter, leaving the field, or using the
 * icon button. */
export function SearchField({
  label,
  placeholder,
  defaultValue,
  onCommit,
}: {
  label: string;
  placeholder: string;
  defaultValue: string;
  onCommit: (value: string) => void;
}) {
  const id = useId();
  const [value, setValue] = useState(defaultValue);
  const lastCommittedValue = useRef(defaultValue.trim());

  useEffect(() => {
    setValue(defaultValue);
    lastCommittedValue.current = defaultValue.trim();
  }, [defaultValue]);

  const commit = useCallback((candidate: string) => {
    const normalized = candidate.trim();
    if (normalized === lastCommittedValue.current) return;
    lastCommittedValue.current = normalized;
    onCommit(normalized);
  }, [onCommit]);

  useEffect(() => {
    if (value.trim() === lastCommittedValue.current) return;
    const timeout = window.setTimeout(() => commit(value), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timeout);
  }, [commit, value]);

  return (
    <div className="field-search">
      <label className="visually-hidden" htmlFor={id}>
        {label}
      </label>
      <button
        type="button"
        className="field-search-submit"
        aria-label="Submit search"
        onClick={() => commit(value)}
      >
        <Search size={16} aria-hidden="true" />
      </button>
      <input
        id={id}
        type="search"
        className="control"
        placeholder={placeholder}
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onBlur={(event) => commit(event.target.value)}
        onKeyDown={(event) => {
          if (event.key !== "Enter") return;
          event.preventDefault();
          commit(event.currentTarget.value);
        }}
      />
    </div>
  );
}
