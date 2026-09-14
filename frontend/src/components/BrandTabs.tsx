import { NavLink } from "react-router-dom";

const TABS = [
  ["Overview", ""],
  ["Menu", "/menu"],
  ["Promotions", "/promotions"],
  ["Changes", "/changes"],
  ["History", "/history"],
];

export function BrandTabs({ brandId }: { brandId: string }) {
  const base = `/competitors/${brandId}`;
  return (
    <div className="tabs">
      {TABS.map(([label, suffix]) => (
        <NavLink
          key={label}
          to={`${base}${suffix}`}
          end={suffix === ""}
          className={({ isActive }) => (isActive ? "active" : "")}
        >
          {label}
        </NavLink>
      ))}
    </div>
  );
}
