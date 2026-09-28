import { Search } from "lucide-react";
import { useId } from "react";

/** Labeled search input with a leading icon. Commits on blur, matching the
 * existing product/history filter behavior (no per-keystroke fetch). */
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
  return (
    <div className="field-search">
      <label className="visually-hidden" htmlFor={id}>
        {label}
      </label>
      <Search size={16} aria-hidden="true" />
      <input
        id={id}
        className="control"
        placeholder={placeholder}
        defaultValue={defaultValue}
        onBlur={(event) => onCommit(event.target.value)}
      />
    </div>
  );
}
