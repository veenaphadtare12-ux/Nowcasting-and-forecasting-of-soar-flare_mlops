import "@fontsource-variable/sora/wght";
import "@fontsource/ibm-plex-sans/400";
import "@fontsource/ibm-plex-sans/500";
import "@fontsource/ibm-plex-sans/600";
import "@fontsource/ibm-plex-mono/400";
import "@fontsource/ibm-plex-mono/500";
import { type ReactNode, Suspense, lazy } from "react";
import { Link, NavLink, Navigate, Route, Routes } from "react-router-dom";
import type { Health } from "./api";
import { useApi } from "./hooks";
import About from "./pages/About";
import DataDrift from "./pages/DataDrift";
import Latest from "./pages/Latest";
import ModelsPipeline from "./pages/ModelsPipeline";
import Performance from "./pages/Performance";
import Replay from "./pages/Replay";

const Landing = lazy(() => import("./landing/Landing"));

const icon = (d: ReactNode) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {d}
  </svg>
);
const NAV: { to: string; label: string; icon: ReactNode }[] = [
  { to: "/latest", label: "Latest", icon: icon(<path d="M3 12h4l3-8 4 16 3-8h4" />) },
  { to: "/replay", label: "Replay", icon: icon(<><circle cx="12" cy="12" r="9" /><path d="m10 8.5 5 3.5-5 3.5z" /></>) },
  { to: "/performance", label: "Performance", icon: icon(<path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />) },
  { to: "/models", label: "Models & pipeline", icon: icon(<><path d="m12 3 9 5-9 5-9-5z" /><path d="m3 13 9 5 9-5" /></>) },
  { to: "/data", label: "Data & drift", icon: icon(<><ellipse cx="12" cy="5.5" rx="8" ry="2.5" /><path d="M4 5.5v13c0 1.4 3.6 2.5 8 2.5s8-1.1 8-2.5v-13M4 12c0 1.4 3.6 2.5 8 2.5s8-1.1 8-2.5" /></>) },
  { to: "/about", label: "About", icon: icon(<><circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 7.5v.01" /></>) },
];

function Mark() {
  return (
    <svg viewBox="0 0 32 32" className="h-8 w-8" aria-hidden="true">
      <circle cx="16" cy="16" r="15" fill="none" stroke="rgba(94,234,212,0.35)" />
      <circle cx="16" cy="16" r="6.5" fill="#F5B544" />
      <circle cx="16" cy="16" r="10.5" fill="none" stroke="#5EEAD4" strokeWidth="1.2" strokeDasharray="2 3" />
    </svg>
  );
}

function SystemStatus() {
  const health = useApi<Health>("/health", 30000);
  const h = health.data;
  const state = h ? "online" : health.error ? "offline" : "connecting";
  const dot = h ? "bg-accent shadow-[0_0_10px_rgba(94,234,212,.8)]" : health.error ? "bg-coral" : "bg-amber";
  return (
    <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3.5">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-dim">System</span>
        <span className="flex items-center gap-1.5 font-mono text-[11px] text-muted">
          <i className={`h-1.5 w-1.5 rounded-full ${dot}`} />
          {state}
        </span>
      </div>
      {h && (
        <dl className="mt-3 space-y-1.5 font-mono text-[11px]">
          {[
            ["models", `${h.models_loaded.length} champions`],
            ["bundle", h.bundle_version],
            ["env", h.environment],
            ["image", h.image_git_sha.slice(0, 7)],
          ].map(([k, v]) => (
            <div key={k} className="flex justify-between gap-2">
              <dt className="text-dim">{k}</dt>
              <dd className="truncate text-muted">{v}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

function Shell() {
  return (
    <div className="console-bg min-h-full lg:flex">
      <aside className="sticky top-0 z-20 border-b border-white/[0.06] bg-ink-950/85 backdrop-blur lg:flex lg:h-screen lg:w-[248px] lg:shrink-0 lg:flex-col lg:border-r lg:border-b-0 lg:bg-ink-950/60">
        <div className="flex items-center gap-3 px-5 py-4 lg:py-6">
          <Link to="/" className="flex items-center gap-3" title="Back to the story">
            <Mark />
            <div>
              <div className="font-display text-[15px] font-semibold tracking-[-0.01em] text-fg">Flare Watch</div>
              <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-dim">Aditya-L1 console</div>
            </div>
          </Link>
        </div>
        <nav aria-label="Console" className="flex gap-1 overflow-x-auto px-3 pb-3 lg:flex-col lg:overflow-visible lg:px-5 lg:pb-0">
          <div className="hidden px-3 pb-2 font-mono text-[10px] uppercase tracking-[0.18em] text-dim lg:block">Monitor</div>
          {NAV.map((n, i) => (
            <div key={n.to} className="contents">
              {i === 2 && <div className="hidden px-3 pt-4 pb-2 font-mono text-[10px] uppercase tracking-[0.18em] text-dim lg:block">Evidence</div>}
              {i === 5 && <div className="hidden px-3 pt-4 pb-2 font-mono text-[10px] uppercase tracking-[0.18em] text-dim lg:block">Project</div>}
              <NavLink to={n.to} className={({ isActive }) => `nav-item whitespace-nowrap ${isActive ? "active" : ""}`}>
                {n.icon}
                {n.label}
              </NavLink>
            </div>
          ))}
        </nav>
        <div className="mt-auto hidden space-y-3 p-5 lg:block">
          <SystemStatus />
          <Link to="/" className="flex items-center gap-2 px-1 font-mono text-[11px] text-dim transition hover:text-accent">
            ← Back to the story
          </Link>
          <p className="px-1 text-[10.5px] leading-snug text-dim/80">Research system · not an operational alert service</p>
        </div>
      </aside>
      <main className="min-w-0 flex-1 px-5 py-7 lg:px-10 lg:py-9">
        <div className="mx-auto max-w-[1500px] space-y-6">
          <Routes>
            <Route path="/latest" element={<Latest />} />
            <Route path="/replay" element={<Replay />} />
            <Route path="/performance" element={<Performance />} />
            <Route path="/models" element={<ModelsPipeline />} />
            <Route path="/data" element={<DataDrift />} />
            <Route path="/about" element={<About />} />
            <Route path="*" element={<Navigate to="/latest" replace />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route
        path="/"
        element={
          <Suspense fallback={<div className="grid h-screen place-items-center bg-[#03050b] font-mono text-xs tracking-[0.2em] text-slate-500 uppercase">Approaching the Sun</div>}>
            <Landing />
          </Suspense>
        }
      />
      <Route path="*" element={<Shell />} />
    </Routes>
  );
}
