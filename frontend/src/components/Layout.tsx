import { Activity, Gauge, Store, Tag } from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";
import { useApi } from "../api/useApi";
import { api } from "../api/client";
import type { Brand } from "../api/types";
import kuduLogo from "../assets/kudu-logo-horizontal.png";

const COMPETITORS = [
  { id: "kfc", name: "KFC", to: "/competitors/kfc" },
  { id: "hardees", name: "Hardee's", to: "/competitors/hardees" },
  { id: "burger-king", name: "Burger King", to: "/competitors/burger-king" },
  { id: "herfy", name: "Herfy", to: "/competitors/herfy" },
];

export function Layout() {
  const { data } = useApi(() => api.brands(), []);
  const brands = new Map((data?.items ?? []).map((b: Brand) => [b.id, b]));

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <img src={kuduLogo} alt="KUDU" className="sidebar-logo" />
          <span>Price Intelligence</span>
        </div>
        <nav className="nav-group" aria-label="Market">
          <div className="nav-group-label">Overview</div>
          <NavLink to="/overview" className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
            <Gauge size={18} aria-hidden="true" />
            Market Overview
          </NavLink>
          <NavLink to="/changes" className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
            <Activity size={18} aria-hidden="true" />
            Market Changes
          </NavLink>
          <NavLink to="/promotions" className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
            <Tag size={18} aria-hidden="true" />
            Promotions
          </NavLink>
        </nav>
        <nav className="nav-group" aria-label="Competitors">
          <div className="nav-group-label">Competitors</div>
          {COMPETITORS.map((item) => {
            const brand = brands.get(item.id);
            const connected = brand ? brand.health !== "disconnected" : item.id === "kfc";
            return (
              <NavLink
                key={item.id}
                to={item.to}
                className={({ isActive }) => `nav-link${isActive ? " active" : ""}${connected ? "" : " dim"}`}
              >
                <Store size={18} aria-hidden="true" />
                <span>{item.name}</span>
                {!connected && <span className="nav-link-status">Not connected</span>}
              </NavLink>
            );
          })}
        </nav>
      </aside>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
