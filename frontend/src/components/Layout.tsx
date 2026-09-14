import { NavLink, Outlet } from "react-router-dom";
import { useApi } from "../api/useApi";
import { api } from "../api/client";
import type { Brand } from "../api/types";

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
        <div className="brand-mark" aria-label="Kudu Price Intelligence">
          <strong>KUDU</strong>
          PRICE INTELLIGENCE
        </div>
        <nav className="nav-section">
          <div className="nav-label">OVERVIEW</div>
          <NavLink to="/overview" className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
            Market Overview
          </NavLink>
          <NavLink to="/changes" className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
            Market Changes
          </NavLink>
          <NavLink to="/promotions" className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
            Promotions
          </NavLink>
        </nav>
        <nav className="nav-section">
          <div className="nav-label">COMPETITORS</div>
          {COMPETITORS.map((item) => {
            const brand = brands.get(item.id);
            const connected = brand ? brand.health !== "disconnected" : item.id === "kfc";
            return (
              <NavLink
                key={item.id}
                to={item.to}
                className={({ isActive }) => `nav-link${isActive ? " active" : ""}${connected ? "" : " dim"}`}
              >
                <span>{item.name}</span>
                {!connected && <span className="nav-status">Not connected</span>}
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
