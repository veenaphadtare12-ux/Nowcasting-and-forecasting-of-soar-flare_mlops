import type * as echarts from "echarts";
import { useMemo } from "react";
import type { Coverage, Drift } from "../api";
import { HEL1OS, SOLEXS, fmtPct } from "../api";
import Chart, { axisStyle } from "../components/Chart";
import { Card, ErrorBox, Loading, Pill, SourceNote, Stat } from "../components/ui";
import { useApi } from "../hooks";

function calendar(c: Coverage): echarts.EChartsOption {
  const years = Array.from(new Set(c.days.map((d) => d.slice(0, 4))));
  const data = c.days.map((d, i) => [d, c.valid_fraction[i]]);
  return {
    animation: false,
    tooltip: { formatter: (p: unknown) => { const v = (p as { value: [string, number] }).value; return `${v[0]}: ${fmtPct(v[1], 0)} valid`; } },
    visualMap: { min: 0, max: 1, orient: "horizontal", left: "center", bottom: 0, inRange: { color: ["#111827", "#5a3412", SOLEXS] }, textStyle: { color: "#94a3b8" }, text: ["100% valid", "no data"] },
    calendar: years.map((y, i) => ({
      top: 30 + i * 150,
      left: 50,
      right: 20,
      cellSize: ["auto", 15],
      range: y,
      itemStyle: { color: "#0d1420", borderColor: "#070b12", borderWidth: 2 },
      splitLine: { show: false },
      yearLabel: { color: "#94a3b8" },
      monthLabel: { color: "#94a3b8" },
      dayLabel: { color: "#64748b", fontSize: 9 },
    })),
    series: years.map((y, i) => ({ type: "heatmap", coordinateSystem: "calendar", calendarIndex: i, data: data.filter((d) => (d[0] as string).startsWith(y)) })),
  };
}

function monthly(c: Coverage): echarts.EChartsOption {
  const months = Object.keys(c.goes_monthly);
  const colors: Record<string, string> = { B: "#334155", C: "#d9a441", M: SOLEXS, X: "#ef4444" };
  return {
    animation: false,
    tooltip: { trigger: "axis" },
    legend: { top: 0, textStyle: { color: "#cbd5e1" } },
    grid: { left: 44, right: 10, top: 34, bottom: 40 },
    xAxis: { type: "category", data: months, ...axisStyle },
    yAxis: { type: "value", name: "GOES flares", ...axisStyle },
    series: ["B", "C", "M", "X"].map((k) => ({ name: `${k}-class`, type: "bar", stack: "f", data: months.map((m) => c.goes_monthly[m]?.[k] ?? 0), itemStyle: { color: colors[k] } })),
  };
}

function driftBars(d: Drift): echarts.EChartsOption {
  const rows = Object.entries(d.per_feature ?? {})
    .map(([f, v]) => ({ f, s: v.method.includes("p_value") ? 1 - v.score : v.score / Math.max(v.threshold, 1e-9) / 2, drifted: v.drifted, raw: v }))
    .sort((a, b) => b.s - a.s)
    .slice(0, 22)
    .reverse();
  return {
    animation: false,
    tooltip: {
      formatter: (p: unknown) => {
        const r = rows[(p as { dataIndex: number }).dataIndex];
        return `${r.f}<br/>${r.raw.method}: ${r.raw.score.toPrecision(3)} (threshold ${r.raw.threshold})<br/>${r.drifted ? "drifted" : "no drift"}`;
      },
    },
    grid: { left: 170, right: 20, top: 10, bottom: 30 },
    xAxis: { type: "value", name: "relative drift", ...axisStyle },
    yAxis: { type: "category", data: rows.map((r) => r.f), ...axisStyle, axisLabel: { color: "#cbd5e1", fontSize: 10 } },
    series: [{ type: "bar", data: rows.map((r) => ({ value: Number(r.s.toFixed(3)), itemStyle: { color: r.drifted ? (r.f.startsWith("hx_") || r.f === "hel1os_available" ? HEL1OS : "#ef4444") : "#475569" } })) }],
  };
}

export default function DataDrift() {
  const cov = useApi<Coverage>("/data/coverage");
  const drift = useApi<Drift>("/drift/latest", 60000);
  const calOpt = useMemo(() => (cov.data ? calendar(cov.data) : null), [cov.data]);
  const monOpt = useMemo(() => (cov.data ? monthly(cov.data) : null), [cov.data]);
  const driftOpt = useMemo(() => (drift.data ? driftBars(drift.data) : null), [drift.data]);

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-2xl font-semibold text-slate-100">Data and drift</h1>
        <p className="text-sm text-slate-400">How much Aditya-L1 SoLEXS data we have, how active the Sun was, and whether today's inputs still look like the training data.</p>
      </header>
      {cov.error && <ErrorBox error={cov.error} onRetry={cov.reload} />}
      {cov.loading && <Loading height={300} />}
      {cov.data && calOpt && monOpt && (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <Stat label="Days in the development period" value={cov.data.summary.days} sub={`${cov.data.periods.tune[0]} … ${cov.data.periods.test[1]}`} />
            <Stat label="Usable SoLEXS days" value={cov.data.summary.usable_days} sub="at least half the day observed" />
            <Stat label="Mean valid fraction" value={fmtPct(cov.data.summary.mean_valid_fraction, 0)} sub="share of seconds with good data" />
          </div>
          <Card title="SoLEXS coverage calendar">
            <Chart option={calOpt} height={360} />
            <SourceNote>{cov.data.note} The 17th of each month is regularly almost empty.</SourceNote>
          </Card>
          <Card title="GOES flares per month">
            <Chart option={monOpt} height={280} />
          </Card>
        </>
      )}
      <Card title="Feature drift (Evidently)" right={drift.data && (drift.data.drift_flag ? <Pill tone="red">drift flagged</Pill> : <Pill tone="green">no dataset drift</Pill>)}>
        {drift.error && <ErrorBox error={drift.error} onRetry={drift.reload} />}
        {drift.loading && !drift.data && <Loading />}
        {drift.data && driftOpt && (
          <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
            <div className="space-y-3">
              <Stat label="Features drifted" value={`${drift.data.drifted_features.length} / ${drift.data.features_checked}`} sub={`share ${fmtPct(drift.data.drifted_share, 0)} (flag at 50%)`} />
              <div className="text-xs text-slate-400">
                <div><b>Reference:</b> {drift.data.reference_label ?? drift.data.reference_window?.map((x) => x.slice(0, 10)).join(" … ")}</div>
                <div><b>Current:</b> {drift.data.current_label ?? drift.data.current_window?.map((x) => x.slice(0, 10)).join(" … ")}</div>
                <div className="mt-1">Source: {drift.data.source}</div>
              </div>
              <p className="text-xs text-slate-500">
                Blue bars are HEL1OS features: they drift mostly because HEL1OS observes in sessions on some days only, not because the Sun changed.
              </p>
            </div>
            <Chart option={driftOpt} height={520} />
          </div>
        )}
      </Card>
    </div>
  );
}
