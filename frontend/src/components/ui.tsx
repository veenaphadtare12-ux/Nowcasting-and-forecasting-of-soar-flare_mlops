import type { ReactNode } from "react";
import { TARGET_LABEL, fmtPct } from "../api";

export function Card({ title, right, children, className = "" }: { title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {(title || right) && (
        <div className="card-title">
          <span>{title}</span>
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

export function Loading({ label = "Loading…", height = 160 }: { label?: string; height?: number }) {
  return (
    <div className="flex animate-pulse items-center justify-center rounded-lg bg-ink-800/60 text-sm text-slate-500" style={{ height }} role="status">
      {label}
    </div>
  );
}

export function ErrorBox({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div className="rounded-lg border border-red-500/40 bg-red-950/40 p-3 text-sm text-red-200" role="alert">
      <div className="font-semibold">Could not load data</div>
      <div className="mono mt-1 break-words text-red-300/90">{error}</div>
      {onRetry && (
        <button className="btn mt-2" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

const PILL: Record<string, string> = {
  green: "bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30",
  red: "bg-red-500/15 text-red-300 ring-1 ring-red-500/30",
  amber: "bg-amber-500/15 text-amber-200 ring-1 ring-amber-500/30",
  blue: "bg-hel1os/20 text-blue-200 ring-1 ring-hel1os/40",
  slate: "bg-slate-500/15 text-slate-300 ring-1 ring-slate-500/30",
  orange: "bg-solexs/15 text-orange-200 ring-1 ring-solexs/40",
};
export function Pill({ tone = "slate", children }: { tone?: keyof typeof PILL; children: ReactNode }) {
  return <span className={`pill ${PILL[tone]}`}>{children}</span>;
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="rounded-lg border border-ink-700 bg-ink-800/60 px-3 py-2">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-0.5 text-lg font-semibold text-slate-100">{value}</div>
      {sub && <div className="text-xs text-slate-400">{sub}</div>}
    </div>
  );
}

/** Horizontal probability gauge with the alert threshold marked. */
export function Gauge({ target, p, threshold, color }: { target: string; p: number | null; threshold: number; color: string }) {
  const alert = p != null && p >= threshold;
  return (
    <div className={`rounded-lg border px-3 py-2 transition ${alert ? "border-red-500/60 bg-red-950/30" : "border-ink-700 bg-ink-800/50"}`}>
      <div className="flex items-baseline justify-between text-xs">
        <span className="text-slate-300">{TARGET_LABEL[target] ?? target}</span>
        <span className={`font-mono text-sm ${alert ? "text-red-300" : "text-slate-100"}`}>{fmtPct(p, 0)}</span>
      </div>
      <div className="relative mt-1.5 h-2.5 rounded-full bg-ink-700" aria-label={`${target} probability`}>
        <div className="h-2.5 rounded-full transition-[width] duration-200" style={{ width: `${Math.min(100, (p ?? 0) * 100)}%`, background: alert ? "#ef4444" : color }} />
        <div className="absolute -top-1 h-4.5 w-0.5 bg-slate-100" style={{ left: `${threshold * 100}%` }} title={`alert threshold ${fmtPct(threshold, 0)}`} />
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-slate-500">
        <span>threshold {fmtPct(threshold, 0)}</span>
        {alert ? <span className="font-semibold text-red-300">ALERT</span> : <span>no alert</span>}
      </div>
    </div>
  );
}

export function SourceNote({ children }: { children: ReactNode }) {
  return <p className="mt-2 text-xs text-slate-500">{children}</p>;
}
