import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { api, useApi, type Integrity, type Meta } from "../lib/api";
import { Mark } from "./ui";

const NAV = [
  { to: "/cases", label: "Cases" },
  { to: "/violations", label: "Violations" },
  { to: "/integrity", label: "Integrity" },
  { to: "/experiments", label: "Experiments" },
  { to: "/method", label: "Method" },
];

type Theme = "system" | "light" | "dark";

function readTheme(): Theme {
  try {
    const t = localStorage.getItem("casefile-theme");
    return t === "light" || t === "dark" ? t : "system";
  } catch {
    return "system";
  }
}

function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(readTheme);
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("casefile-theme", theme);
    } catch {
      /* storage unavailable: the preference lasts for this page view */
    }
  }, [theme]);
  const next: Record<Theme, Theme> = { system: "light", light: "dark", dark: "system" };
  return (
    <button className="btn ghost" type="button" onClick={() => setTheme(next[theme])} aria-label={`Theme: ${theme}. Switch to ${next[theme]}`}>
      Theme: {theme}
    </button>
  );
}

function ChainStatus() {
  const integrity = useApi<Integrity>(api.integrity);
  if (integrity.error) return <Mark tone="neutral" glyph="?">Chain status unavailable</Mark>;
  if (!integrity.data) return <span className="muted small">Verifying chain…</span>;
  return (
    <NavLink to="/integrity" style={{ textDecoration: "none" }}>
      {integrity.data.valid ? (
        <Mark tone="ok" glyph="✓" title={`${integrity.data.events} events verified`}>
          Chain intact
        </Mark>
      ) : (
        <Mark tone="bad" glyph="✕">
          Chain broken at {integrity.data.first_bad_seq}
        </Mark>
      )}
    </NavLink>
  );
}

function Deployment() {
  const meta = useApi<Meta>(api.meta);
  const d = meta.data?.deployment;
  if (!meta.data || !d) return null;
  return (
    <span className="deployment">
      World seed <span className="mono">{d.seed}</span> · {meta.data.decisions.toLocaleString("en-GB")} decisions · agent{" "}
      {d.variant === "faulty" ? "with injected violations" : "clean"}
    </span>
  );
}

export function Layout() {
  const location = useLocation();
  useEffect(() => {
    // Move focus to the page on navigation so keyboard and screen-reader users land on content.
    document.getElementById("main")?.focus({ preventScroll: true });
  }, [location.pathname]);
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="topbar">
        <div className="topbar-inner">
          <div className="topbar-row">
            <NavLink to="/cases" className="brand" aria-label="Casefile, decision list">
              <span className="brand-mark" aria-hidden="true">
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <path d="M3 2.5h7l3 3v8H3z" strokeLinejoin="round" />
                  <path d="M5.5 7.5h5M5.5 10h3.5" strokeLinecap="round" />
                </svg>
              </span>
              <span>
                <span className="brand-name">Casefile</span>
                <br />
                <span className="brand-sub">agent decision audit</span>
              </span>
            </NavLink>
            <Deployment />
            <ChainStatus />
            <ThemeToggle />
          </div>
          <nav className="tabs" aria-label="Sections">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} className={({ isActive }) => (isActive ? "active" : "")}>
                {n.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <main id="main" className="main" tabIndex={-1}>
        <Outlet />
      </main>
    </>
  );
}
