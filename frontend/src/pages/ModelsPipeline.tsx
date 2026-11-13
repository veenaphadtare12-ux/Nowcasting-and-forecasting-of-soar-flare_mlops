import type * as echarts from "echarts";
import { useMemo } from "react";
import type { ModelInfo, PipelineStatus, Results } from "../api";
import { TARGET_LABEL, fmt, fmtPct } from "../api";
import Chart from "../components/Chart";
import PipelinePanel from "../components/PipelinePanel";
import { Card, ErrorBox, Loading, Pill, SourceNote } from "../components/ui";
import { useApi } from "../hooks";

/** DVC stages laid out left-to-right by dependency depth. */
function dagOption(p: PipelineStatus): echarts.EChartsOption {
  const names = p.dvc.stages.map((s) => s.name);
  const parents = new Map<string, string[]>(names.map((n) => [n, []]));
  p.dvc.edges.forEach(([a, b]) => parents.get(b)?.push(a));
  const depth = new Map<string, number>();
  const d = (n: string, seen = new Set<string>()): number => {
    if (depth.has(n)) return depth.get(n)!;
    if (seen.has(n)) return 0;
    seen.add(n);
    const v = Math.max(0, ...(parents.get(n) ?? []).map((x) => d(x, seen) + 1));
    depth.set(n, v);
    return v;
  };
  names.forEach((n) => d(n));
  const cols = new Map<number, string[]>();
  names.forEach((n) => cols.set(depth.get(n)!, [...(cols.get(depth.get(n)!) ?? []), n]));
  const frozen = new Set(p.dvc.stages.filter((s) => s.frozen).map((s) => s.name));
  const nodes = names.map((n) => {
    const c = depth.get(n)!;
    const i = cols.get(c)!.indexOf(n);
    return {
      name: n,
      x: c * 190,
      y: i * 46,
      symbol: "roundRect",
      symbolSize: [170, 30],
      itemStyle: { color: frozen.has(n) ? "#1e2a3d" : "#3a2a17", borderColor: frozen.has(n) ? "#2B5DA8" : "#E07A1F", borderWidth: 1.4 },
      label: { show: true, color: "#e2e8f0", fontSize: 10 },
    };
  });
  return {
    animation: false,
    tooltip: { formatter: (x: unknown) => { const n = (x as { name: string }).name; return `${n}<br/>${frozen.has(n) ? "frozen (never re-run)" : "data stage (re-runs on change)"}`; } },
    series: [
      {
        type: "graph",
        layout: "none",
        roam: true,
        data: nodes,
        links: p.dvc.edges.map(([s, t]) => ({ source: s, target: t })),
        edgeSymbol: ["none", "arrow"],
        edgeSymbolSize: 6,
        lineStyle: { color: "#475569", width: 1, curveness: 0.12, opacity: 0.8 },
      },
    ],
  };
}

export default function ModelsPipeline() {
  const models = useApi<ModelInfo[]>("/models");
  const status = useApi<PipelineStatus>("/pipeline/status", 30000);
  const results = useApi<Results>("/results");
  const dag = useMemo(() => (status.data ? dagOption(status.data) : null), [status.data]);

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-2xl font-semibold text-slate-100">Models and pipeline</h1>
        <p className="text-sm text-slate-400">One source of truth: the MLflow registry alias <span className="mono">champion</span>, exported to the versioned model bundle that the API, the flows and Kubernetes load.</p>
      </header>
      <PipelinePanel />
      <Card title="Champion models">
        {models.error && <ErrorBox error={models.error} onRetry={models.reload} />}
        {models.loading && <Loading />}
        {models.data && (
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr><th>Target</th><th>Registry</th><th>Learner</th><th>Inputs</th><th>Threshold A / B / C</th><th>Trained on</th><th>Test TSS</th><th>Challenger</th></tr>
              </thead>
              <tbody>
                {models.data.map((m) => (
                  <tr key={m.target}>
                    <td>{TARGET_LABEL[m.target] ?? m.target}</td>
                    <td className="mono">{m.registry_name} <Pill tone="green">champion v{m.version}</Pill></td>
                    <td>{m.learner}{m.ideas.length ? <span className="text-xs text-slate-400"> + {m.ideas.join(", ")}</span> : null}<div className="text-xs text-slate-500">{m.n_features} features</div></td>
                    <td>{m.inputs === "Aditya-only" ? <Pill tone="orange">Aditya-only</Pill> : <Pill tone="blue">+ GOES XRS</Pill>}</td>
                    <td className="mono">
                      {(["A", "B", "C"] as const).map((k) => (m.thresholds[k] == null ? "n/a" : fmtPct(m.thresholds[k], 0))).join(" / ")}
                    </td>
                    <td className="mono text-xs">{m.fit_dates?.slice(0, 10)} … {m.fit_dates?.split(" .. ")[1]?.slice(0, 10)}</td>
                    <td className="mono text-xs">{m.test_tss_A ?? "–"}</td>
                    <td>{m.challenger ? <Pill tone="amber">v{m.challenger.version} waiting</Pill> : <span className="text-xs text-slate-500">none</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <SourceNote>
              Thresholds: A = max TSS, B = max HSS, C = lowest with FAR ≤ 0.80 ("n/a" = unreachable for M flares), all chosen on May 2026 only. A challenger is
              never promoted automatically.
            </SourceNote>
          </div>
        )}
      </Card>
      {results.data && (
        <Card title="Model card (headline)">
          <div className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-5">
            {Object.entries(results.data.test.targets).map(([t, r]) => (
              <div key={t} className="rounded-lg border border-ink-700 bg-ink-800/50 p-3">
                <div className="text-xs text-slate-400">{TARGET_LABEL[t] ?? t}</div>
                <div className="mt-1 font-mono text-lg text-slate-100">TSS {fmt(r.tss, 2)}</div>
                <div className="text-xs text-slate-400">95% [{fmt(r.ci95?.[0], 2)}, {fmt(r.ci95?.[1], 2)}] · FAR {fmtPct(r.far, 0)}</div>
              </div>
            ))}
          </div>
          <SourceNote>Intended use: research and teaching, a decision aid next to NOAA SWPC; not an operational alert service. Full card: docs/MODEL_CARD.md.</SourceNote>
        </Card>
      )}
      <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
        <Card title="DVC pipeline" right={status.data && <span className="text-[11px] normal-case tracking-normal text-slate-500">{status.data.dvc.total} stages · {status.data.dvc.frozen} frozen (blue)</span>}>
          {status.error && <ErrorBox error={status.error} onRetry={status.reload} />}
          {dag ? <Chart option={dag} height={520} /> : <Loading height={520} />}
          <SourceNote>Orange = data stages (re-run by daily_ingest when inputs change). Blue = model and evaluation stages, frozen so nothing is ever retrained or re-scored by accident. Drag to pan, scroll to zoom.</SourceNote>
        </Card>
        <div className="space-y-4">
          <Card title="Prefect deployments and runs">
            {status.data?.prefect.configured === false && <p className="text-sm text-slate-400">No Prefect server configured (running from the bundle only).</p>}
            {status.data?.prefect.deployments && (
              <ul className="mb-3 space-y-1 text-sm">
                {status.data.prefect.deployments.map((d) => (
                  <li key={d.name} className="flex justify-between"><span className="mono">{d.name}</span><span className="mono text-xs text-slate-400">{d.schedules.filter(Boolean).join(", ") || "on demand"}</span></li>
                ))}
              </ul>
            )}
            {status.data?.prefect.recent_runs?.length ? (
              <table className="tbl">
                <thead><tr><th>Flow</th><th>State</th><th>Started</th></tr></thead>
                <tbody>
                  {status.data.prefect.recent_runs.slice(0, 8).map((r, i) => (
                    <tr key={i}><td className="mono">{r.flow}</td><td><Pill tone={r.state === "Completed" ? "green" : r.state === "Failed" ? "red" : "amber"}>{r.state}</Pill></td><td className="mono text-xs">{r.start?.slice(0, 16).replace("T", " ")}</td></tr>
                  ))}
                </tbody>
              </table>
            ) : (
              status.data?.prefect.configured && <p className="text-sm text-slate-400">No flow runs yet.</p>
            )}
            {status.data?.prefect.ui && <SourceNote>Prefect UI: <a className="text-orange-300 underline" href="http://localhost:4200" target="_blank" rel="noreferrer">localhost:4200</a> · MLflow: <a className="text-orange-300 underline" href="http://localhost:5000" target="_blank" rel="noreferrer">localhost:5000</a></SourceNote>}
          </Card>
          <Card title="MLOps tools">
            <ul className="grid grid-cols-1 gap-1 text-sm sm:grid-cols-2">
              {status.data?.tools.map((t) => (
                <li key={t.tool} className="flex items-center justify-between gap-2 rounded bg-ink-800/50 px-2 py-1">
                  <span>{t.tool}</span>
                  <Pill tone={t.status === "used" ? "green" : "amber"}>{t.status}</Pill>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>
    </div>
  );
}
