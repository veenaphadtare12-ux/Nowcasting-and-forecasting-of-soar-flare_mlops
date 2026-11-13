import type { ReactNode } from "react";
import { TARGET_LABEL, fmtPct } from "../api";

/** Page title block: small eyebrow, title, one short line. Optional content on the right. */
export function PageHeader({ eyebrow, title, sub, right }: { eyebrow: string; title: string; sub?: ReactNode; right?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4 pb-2">
      <div>
        <div className="font-mono text-[11px] uppercase tracking-[0.18em] text-accent">{eyebrow}</div>
        <h1 className="font-display mt-2 text-[30px] font-semibold leading-tight tracking-[-0.02em] text-fg">{title}</h1>
        {sub && <p className="mt-1.5 text-[15px] text-muted">{sub}</p>}
      </div>
      {right}
    </header>
  );
}

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

export function Loading({ label = "Loading", height = 160 }: { label?: string; height?: number }) {
  return (
    <div className="skeleton" style={{ height }} role="status">
      <span className="sr-only">{label}</span>
    </div>
  );
}

export function ErrorBox({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-coral/30 bg-coral/[0.06] px-4 py-3 text-sm" role="alert">
      <div>
        <div className="font-medium text-coral">Couldn't load this panel</div>
        <div className="mono mt-0.5 break-words text-muted">{error}</div>
      </div>
      {onRetry && (
        <button className="btn" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

const PILL: Record<string, string> = {
  green: "bg-accent/10 text-accent",
  red: "bg-coral/12 text-coral",
  amber: "bg-amber/12 text-amber",
  blue: "bg-peri/12 text-peri",
  slate: "bg-white/[0.06] text-muted",
  orange: "bg-amber/12 text-amber",
};
export function Pill({ tone = "slate", children }: { tone?: keyof typeof PILL; children: ReactNode }) {
  return <span className={`pill ${PILL[tone]}`}>{children}</span>;
}

/** Key figure: small label, large tabular value, quiet sub-line. */
export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="rounded-xl border border-white/[0.07] bg-ink-900/70 px-4 py-3.5">
      <div className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-dim">{label}</div>
      <div className="font-display mt-1.5 text-[22px] font-semibold tracking-[-0.01em] text-fg tabular-nums">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted">{sub}</div>}
    </div>
  );
}

/** Probability bar with the alert threshold marked. */
export function Gauge({ target, p, threshold, color }: { target: string; p: number | null; threshold: number; color: string }) {
  const alert = p != null && p >= threshold;
  return (
    <div className={`rounded-xl border px-3.5 py-3 transition ${alert ? "border-coral/40 bg-coral/[0.06]" : "border-white/[0.06] bg-ink-800/40"}`}>
      <div className="flex items-baseline justify-between">
        <span className="text-[13px] text-muted">{TARGET_LABEL[target] ?? target}</span>
        <span className={`font-mono text-[15px] tabular-nums ${alert ? "text-coral" : "text-fg"}`}>{fmtPct(p, 0)}</span>
      </div>
      <div className="relative mt-2 h-1.5 rounded-full bg-white/[0.06]" aria-label={`${target} probability`}>
        <div className="h-1.5 rounded-full transition-[width] duration-200" style={{ width: `${Math.min(100, (p ?? 0) * 100)}%`, background: alert ? "var(--color-coral)" : color }} />
        <div className="absolute -top-1 h-3.5 w-[2px] rounded bg-fg/70" style={{ left: `${threshold * 100}%` }} title={`alert threshold ${fmtPct(threshold, 0)}`} />
      </div>
      <div className="mt-1.5 flex justify-between font-mono text-[10px] uppercase tracking-wider text-dim">
        <span>thr {fmtPct(threshold, 0)}</span>
        {alert ? <span className="text-coral">alert</span> : <span>clear</span>}
      </div>
    </div>
  );
}

/** One quiet line under a chart. Keep it short. */
export function SourceNote({ children }: { children: ReactNode }) {
  return <p className="mt-3 text-xs text-dim">{children}</p>;
}

/** Longer explanations live here, collapsed by default. */
export function Notes({ title = "Notes", children }: { title?: string; children: ReactNode }) {
  return (
    <details className="notes mt-4">
      <summary>{title}</summary>
      <div className="mt-2 space-y-1.5 text-[13px] leading-relaxed text-muted">{children}</div>
    </details>
  );
}
