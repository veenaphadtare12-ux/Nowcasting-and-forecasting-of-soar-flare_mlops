import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import type { Health } from "./api";
import { useApi } from "./hooks";
import About from "./pages/About";
import DataDrift from "./pages/DataDrift";
import Latest from "./pages/Latest";
import ModelsPipeline from "./pages/ModelsPipeline";
import Performance from "./pages/Performance";
import Replay from "./pages/Replay";

const NAV = [
  { to: "/latest", label: "Latest" },
  { to: "/replay", label: "Replay" },
  { to: "/performance", label: "Forecast performance" },
  { to: "/models", label: "Models & pipeline" },
  { to: "/data", label: "Data & drift" },
  { to: "/about", label: "About" },
];

export default function App() {
  const health = useApi<Health>("/health", 30000);
  return (
    <div className="flex min-h-full flex-col">
      <header className="sticky top-0 z-20 border-b border-ink-700 bg-ink-950/90 backdrop-blur">
        <div className="mx-auto flex max-w-[1800px] flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2.5">
          <div className="flex items-center gap-2">
            <svg viewBox="0 0 32 32" className="h-7 w-7" aria-hidden>
              <circle cx="16" cy="16" r="8" fill="#E07A1F" />
              <g stroke="#E07A1F" strokeWidth="2" strokeLinecap="round">
                <path d="M16 3v4M16 25v4M3 16h4M25 16h4M7 7l3 3M22 22l3 3M25 7l-3 3M10 22l-3 3" />
              </g>
            </svg>
            <div>
              <div className="text-sm font-semibold text-slate-100">Aditya-L1 Flare Watch</div>
              <div className="text-[11px] text-slate-500">SoLEXS + HEL1OS nowcasts and forecasts</div>
            </div>
          </div>
          <nav className="flex flex-wrap gap-1" aria-label="main">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                className={({ isActive }) =>
                  `rounded-md px-3 py-1.5 text-sm transition ${isActive ? "bg-solexs/20 text-orange-100" : "text-slate-300 hover:bg-ink-800 hover:text-slate-100"}`
                }
              >
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2 text-xs text-slate-400">
            <span className={`h-2 w-2 rounded-full ${health.data ? "bg-emerald-400" : health.error ? "bg-red-500" : "bg-amber-400"}`} />
            {health.data ? (
              <span>
                API ok · bundle {health.data.bundle_version} · {health.data.environment} · image {health.data.image_git_sha.slice(0, 7)}
              </span>
            ) : health.error ? (
              <span>API unreachable</span>
            ) : (
              <span>connecting…</span>
            )}
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-[1800px] flex-1 px-4 py-5">
        <Routes>
          <Route path="/" element={<Navigate to="/latest" replace />} />
          <Route path="/latest" element={<Latest />} />
          <Route path="/replay" element={<Replay />} />
          <Route path="/performance" element={<Performance />} />
          <Route path="/models" element={<ModelsPipeline />} />
          <Route path="/data" element={<DataDrift />} />
          <Route path="/about" element={<About />} />
          <Route path="*" element={<Navigate to="/latest" replace />} />
        </Routes>
      </main>
      <footer className="border-t border-ink-800 px-4 py-3 text-center text-[11px] text-slate-600">
        Research and teaching system, not an operational alert service · data: ISRO Aditya-L1, NOAA SWPC GOES flare list
      </footer>
    </div>
  );
}
