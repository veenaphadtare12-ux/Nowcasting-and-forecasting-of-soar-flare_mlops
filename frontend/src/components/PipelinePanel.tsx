import type { PipelineStatus } from "../api";
import { fmtPct } from "../api";
import { useApi } from "../hooks";
import { Card, ErrorBox, Loading, Pill } from "./ui";

function ago(iso?: string | null): string {
  if (!iso) return "never";
  const h = (Date.now() - new Date(iso).getTime()) / 3.6e6;
  if (h < 1) return `${Math.max(1, Math.round(h * 60))} min ago`;
  if (h < 48) return `${h.toFixed(1)} h ago`;
  return `${(h / 24).toFixed(1)} days ago`;
}

/** Compact status of the whole pipeline: last Prefect run, data freshness, champion versions, drift. */
export default function PipelinePanel({ compact = false }: { compact?: boolean }) {
  const { data, error, loading, reload } = useApi<PipelineStatus>("/pipeline/status", 30000);
  if (error) return <Card title="Pipeline status"><ErrorBox error={error} onRetry={reload} /></Card>;
  if (loading && !data) return <Card title="Pipeline status"><Loading height={140} /></Card>;
  if (!data) return null;

  const runs = data.prefect.recent_runs ?? [];
  const lastIngest = runs.find((r) => r.flow === "daily_ingest");
  const localIngest = data.flow_runs?.daily_ingest;
  const fresh = data.production;
  const champs = data.mlflow.models ?? Object.fromEntries(Object.values(data.registry).map((r) => [r.name, { champion: r.champion, challenger: r.challenger }]));
  const challengers = Object.entries(champs).filter(([, v]) => v.challenger);

  return (
    <Card
      title="Pipeline status"
      right={
        <span className="text-[11px] normal-case tracking-normal text-slate-500">
          bundle {data.bundle.version} · {data.bundle.git_sha.slice(0, 7)}
        </span>
      }
    >
      <div className={`grid gap-3 ${compact ? "sm:grid-cols-2" : "sm:grid-cols-2 xl:grid-cols-4"}`}>
        <div className="rounded-lg border border-ink-700 bg-ink-800/50 p-3">
          <div className="text-xs uppercase tracking-wide text-slate-400">Last daily_ingest</div>
          {lastIngest ? (
            <div className="mt-1 text-sm">
              <Pill tone={lastIngest.state === "Completed" ? "green" : lastIngest.state === "Failed" ? "red" : "amber"}>{lastIngest.state ?? "?"}</Pill>{" "}
              <span className="text-slate-300">{ago(lastIngest.end ?? lastIngest.start)}</span>
            </div>
          ) : localIngest ? (
            <div className="mt-1 text-sm"><Pill tone="green">{localIngest.status}</Pill> <span className="text-slate-300">{ago(localIngest.finished_at)}</span></div>
          ) : (
            <div className="mt-1 text-sm text-slate-400">no run yet</div>
          )}
          <div className="mt-1 text-xs text-slate-500">
            Prefect {data.prefect.configured ? (data.prefect.reachable ? <Pill tone="green">reachable</Pill> : <Pill tone="red">unreachable</Pill>) : <Pill>not configured</Pill>}
            {data.prefect.deployments?.find((d) => d.name.startsWith("daily_ingest"))?.schedules?.[0] && (
              <span className="ml-1 mono">cron {data.prefect.deployments?.find((d) => d.name.startsWith("daily_ingest"))?.schedules?.[0]} UTC</span>
            )}
          </div>
        </div>
        <div className="rounded-lg border border-ink-700 bg-ink-800/50 p-3">
          <div className="text-xs uppercase tracking-wide text-slate-400">Data freshness</div>
          <div className="mt-1 text-sm text-slate-200">
            Latest scored day: <b>{fresh.latest_scored_day ?? "none yet"}</b>
          </div>
          <div className="text-xs text-slate-400">
            {fresh.pending_days.length ? `${fresh.pending_days.length} day(s) waiting` : "nothing waiting"} · production from {fresh.production_start}
          </div>
          {fresh.hours_since_last_scoring != null && <div className="text-xs text-slate-500">scored {fresh.hours_since_last_scoring} h ago</div>}
        </div>
        <div className="rounded-lg border border-ink-700 bg-ink-800/50 p-3">
          <div className="text-xs uppercase tracking-wide text-slate-400">Champions (MLflow)</div>
          <div className="mt-1 flex flex-wrap gap-1">
            {Object.entries(champs).map(([name, v]) => (
              <span key={name} className="mono rounded bg-ink-700 px-1.5 py-0.5 text-slate-300" title={name}>
                {name.replace("flare-", "").replace("forecast-", "")} v{v.champion ?? "?"}
              </span>
            ))}
          </div>
          <div className="mt-1 text-xs text-slate-500">
            {challengers.length ? `${challengers.length} challenger(s) waiting for review` : "no challenger"} ·{" "}
            {data.mlflow.configured ? (data.mlflow.reachable ? "registry reachable" : "registry unreachable") : "bundle copy"}
          </div>
        </div>
        <div className="rounded-lg border border-ink-700 bg-ink-800/50 p-3">
          <div className="text-xs uppercase tracking-wide text-slate-400">Feature drift</div>
          <div className="mt-1 text-sm">
            {data.drift.drift_flag ? <Pill tone="red">drift flagged</Pill> : <Pill tone="green">no dataset drift</Pill>}{" "}
            <span className="text-slate-300">{fmtPct(data.drift.drifted_share, 0)} of features</span>
          </div>
          <div className="text-xs text-slate-500">{data.drift.current_label ?? (data.drift.current_window ? `${data.drift.current_window[0].slice(0, 10)} … ${data.drift.current_window[1].slice(0, 10)}` : "")}</div>
        </div>
      </div>
    </Card>
  );
}
