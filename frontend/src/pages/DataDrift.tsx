import type * as echarts from "echarts";
import { useMemo } from "react";
import type { Coverage, Drift } from "../api";
import { HEL1OS, SOLEXS, fmtPct } from "../api";
import Chart, { axisStyle } from "../components/Chart";
import { Card, ErrorBox, Loading, Notes, PageHeader, Pill, Stat } from "../components/ui";
import { useApi } from "../hooks";

function calendar(c: Coverage): echarts.EChartsOption {
  const years = Array.from(new Set(c.days.map((d) => d.slice(0, 4))));
  const data = c.days.map((d, i) => [d, c.valid_fraction[i]]);
  return {
    animation: false,
    tooltip: { formatter: (p: unknown) => { const v = (p as { value: [string, number] }).value; return `${v[0]}: ${fmtPct(v[1], 0)} valid`; } },
    visualMap: { min: 0, max: 1, orient: "horizontal", left: "center", bottom: 0, inRange: { color: ["#101a2b", "#1d4a46", "#5EEAD4"] }, textStyle: { color: "#8b98ab" }, text: ["100% valid", "no data"] },
    calendar: years.map((y, i) => ({
      top: 30 + i * 150,
      left: 50,
      right: 20,
      cellSize: ["auto", 15],
      range: y,
      itemStyle: { color: "#0b1220", borderColor: "#060a13", borderWidth: 3 },
      splitLine: { show: false },
      yearLabel: { color: "#5b6779", fontFamily: "Sora Variable, sans-serif" },
      monthLabel: { color: "#8b98ab" },
      dayLabel: { color: "#5b6779", fontSize: 9 },
    })),
    series: years.map((y, i) => ({ type: "heatmap", coordinateSystem: "calendar", calendarIndex: i, data: data.filter((d) => (d[0] as string).startsWith(y)) })),
  };
}

function monthly(c: Coverage): echarts.EChartsOption {
  const months = Object.keys(c.goes_monthly);
  const colors: Record<string, string> = { B: "#3B4658", C: SOLEXS, M: "#FF8A5B", X: "#F0627E" };
  return {
    animation: false,
    tooltip: { trigger: "axis" },
    legend: { top: 0 },
    grid: { left: 44, right: 10, top: 34, bottom: 40 },
    xAxis: { type: "category", data: months, ...axisStyle },
    yAxis: { type: "value", name: "GOES flares", ...axisStyle },
    series: ["B", "C", "M", "X"].map((k) => ({ name: `${k}-class`, type: "bar", stack: "f", data: months.map((m) => c.goes_monthly[m]?.[k] ?? 0), itemStyle: { color: colors[k] }, barWidth: "62%" })),
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
    yAxis: { type: "category", data: rows.map((r) => r.f), ...axisStyle, axisLabel: { ...axisStyle.axisLabel, color: "#aeb9c8", fontSize: 10 } },
    series: [{ type: "bar", data: rows.map((r) => ({ value: Number(r.s.toFixed(3)), itemStyle: { borderRadius: [0, 3, 3, 0], color: r.drifted ? (r.f.startsWith("hx_") || r.f === "hel1os_available" ? HEL1OS : "#FF6B6B") : "#2c3a52" } })) }],
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
      <PageHeader eyebrow="Data · inputs" title="Data & drift" sub="Coverage, solar activity and input drift." />
      {cov.error && <ErrorBox error={cov.error} onRetry={cov.reload} />}
      {cov.loading && <Loading height={300} />}
      {cov.data && calOpt && monOpt && (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <Stat label="Development days" value={cov.data.summary.days} sub={`${cov.data.periods.tune[0]} → ${cov.data.periods.test[1]}`} />
            <Stat label="Usable SoLEXS days" value={cov.data.summary.usable_days} sub="≥ 50% observed" />
            <Stat label="Mean valid fraction" value={fmtPct(cov.data.summary.mean_valid_fraction, 0)} />
          </div>
          <Card title="SoLEXS coverage">
            <Chart option={calOpt} height={360} />
            <Notes>{cov.data.note} The 17th of each month is regularly almost empty.</Notes>
          </Card>
          <Card title="GOES flares per month">
            <Chart option={monOpt} height={280} />
          </Card>
        </>
      )}
      <Card title="Feature drift · Evidently" right={drift.data && (drift.data.drift_flag ? <Pill tone="red">drift flagged</Pill> : <Pill tone="green">no dataset drift</Pill>)}>
        {drift.error && <ErrorBox error={drift.error} onRetry={drift.reload} />}
        {drift.loading && !drift.data && <Loading />}
        {drift.data && driftOpt && (
          <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
            <div className="space-y-3">
              <Stat label="Features drifted" value={`${drift.data.drifted_features.length} / ${drift.data.features_checked}`} sub={`${fmtPct(drift.data.drifted_share, 0)} · flag at 50%`} />
              <div className="text-xs text-muted">
                <div><b>Reference:</b> {drift.data.reference_label ?? drift.data.reference_window?.map((x) => x.slice(0, 10)).join(" … ")}</div>
                <div><b>Current:</b> {drift.data.current_label ?? drift.data.current_window?.map((x) => x.slice(0, 10)).join(" … ")}</div>
                <div className="mt-1">Source: {drift.data.source}</div>
              </div>
              <Notes>Periwinkle bars are HEL1OS features: they drift because HEL1OS observes in sessions, not because the Sun changed.</Notes>
            </div>
            <Chart option={driftOpt} height={520} />
          </div>
        )}
      </Card>
    </div>
  );
}
