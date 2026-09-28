import { NavLink } from "react-router-dom";

const TABS = [
  ["Overview", ""],
  ["Menu", "/menu"],
  ["Promotions", "/promotions"],
  ["Changes", "/changes"],
  ["History", "/history"],
];

const KUDU_TABS = [
  ["Menu", "/menu"],
  ["Overview", ""],
  ["Offers", "/promotions"],
];

export function BrandTabs({ brandId }: { brandId: string }) {
  const base = `/competitors/${brandId}`;
  const tabs = brandId === "kudu" ? KUDU_TABS : TABS;
  return (
    <div className="tabs">
      {tabs.map(([label, suffix]) => (
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
