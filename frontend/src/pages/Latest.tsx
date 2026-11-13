import type * as echarts from "echarts";
import { useMemo } from "react";
import type { ProductionLatest, Series } from "../api";
import { SOLEXS, TARGET_COLOR, TARGET_LABEL, fmtPct, hhmm } from "../api";
import Chart, { axisStyle } from "../components/Chart";
import PipelinePanel from "../components/PipelinePanel";
import { Card, ErrorBox, Loading, PageHeader, Pill, Stat } from "../components/ui";
import { useApi } from "../hooks";

function dayChart(d: Extract<ProductionLatest, { status: "ok" }>): echarts.EChartsOption {
  const lc = d.lightcurve.time.map((t, i) => [t, d.lightcurve.solexs_rate[i]]);
  const series: echarts.SeriesOption[] = [
    { name: "SoLEXS counts/s", type: "line", data: lc, showSymbol: false, lineStyle: { width: 1.2, color: SOLEXS }, itemStyle: { color: SOLEXS }, xAxisIndex: 0, yAxisIndex: 0 },
  ];
  Object.entries(d.predictions).forEach(([t, s]: [string, Series]) => {
    series.push({
      name: TARGET_LABEL[t] ?? t,
      type: "line",
      data: s.time.map((x, i) => [x, s.p_flare[i]]),
      showSymbol: false,
      lineStyle: { width: 1.2, color: TARGET_COLOR[t] },
      itemStyle: { color: TARGET_COLOR[t] },
      xAxisIndex: 1,
      yAxisIndex: 1,
      markLine: { silent: true, symbol: "none", lineStyle: { type: "dashed", color: TARGET_COLOR[t], opacity: 0.6 }, data: [{ yAxis: s.threshold }], label: { show: false } },
    });
  });
  return {
    animation: false,
    tooltip: { trigger: "axis" },
    legend: { top: 0 },
    axisPointer: { link: [{ xAxisIndex: "all" }] },
    grid: [
      { left: 60, right: 20, top: 40, height: "38%" },
      { left: 60, right: 20, top: "58%", height: "32%" },
    ],
    xAxis: [
      { type: "time", gridIndex: 0, ...axisStyle, axisLabel: { show: false } },
      { type: "time", gridIndex: 1, ...axisStyle },
    ],
    yAxis: [
      { type: "log", gridIndex: 0, name: "counts/s", ...axisStyle },
      { type: "value", gridIndex: 1, min: 0, max: 1, name: "P(flare)", ...axisStyle },
    ],
    series,
  };
}

export default function Latest() {
  const { data, error, loading, reload } = useApi<ProductionLatest>("/production/latest", 60000);
  const option = useMemo(() => (data && data.status === "ok" ? dayChart(data) : null), [data]);

  return (
    <div className="space-y-4">
      <PageHeader eyebrow="Monitor · production" title="Latest day" sub="Scored automatically every night at 02:15 UTC." />
      <PipelinePanel />
      {error && <ErrorBox error={error} onRetry={reload} />}
      {loading && !data && <Loading height={300} />}
      {data?.status === "no_data" && (
        <Card title="Awaiting the first production day" right={<Pill tone="amber">standby</Pill>}>
          <div className="grid gap-3 sm:grid-cols-3">
            <Stat label="Production starts" value={data.freshness.production_start} />
            <Stat label="Newest raw day" value={data.freshness.latest_available_day ?? "—"} />
            <Stat label="Waiting to score" value={data.freshness.pending_days.length} />
          </div>
        </Card>
      )}
      {data?.status === "ok" && option && (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Day" value={data.day} sub={`scored ${data.summary.scored_at.replace("T", " ").slice(0, 16)} UTC`} />
            <Stat label="Coverage" value={fmtPct(data.summary.valid_fraction, 0)} sub={`${data.summary.rows.toLocaleString()} rows`} />
            <Stat label="GOES flares" value={data.goes_flares.length} />
            <Stat label="Bundle" value={data.summary.bundle_version} />
          </div>
          <Card title="Light curve · flare probability">
            <Chart option={option} height={460} />
          </Card>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Alerts">
              <table className="tbl">
                <thead>
                  <tr><th>Target</th><th>Alerts (min)</th><th>First alert</th><th>Max P</th><th>Threshold</th></tr>
                </thead>
                <tbody>
                  {Object.entries(data.summary.targets).map(([t, v]) => (
                    <tr key={t}>
                      <td>{TARGET_LABEL[t] ?? t}</td>
                      <td>{v.alerts ? <Pill tone="red">{v.alert_minutes} min</Pill> : <Pill tone="green">none</Pill>}</td>
                      <td className="mono">{hhmm(v.first_alert)}</td>
                      <td className="mono">{fmtPct(v.max_p, 0)}</td>
                      <td className="mono">{fmtPct(v.threshold, 0)}</td>
                    </tr>
                  ))}
                  {Object.entries(data.summary.not_scored).map(([t, why]) => (
                    <tr key={t} className="text-dim">
                      <td>{TARGET_LABEL[t] ?? t}</td>
                      <td colSpan={4} className="text-xs">not scored in production: {why}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
            <Card title="GOES flares">
              {data.goes_flares.length ? (
                <table className="tbl">
                  <thead><tr><th>Class</th><th>Begin</th><th>Peak</th><th>End</th></tr></thead>
                  <tbody>
                    {data.goes_flares.map((g, i) => (
                      <tr key={i}><td><Pill tone={g.goes_class?.startsWith("X") || g.goes_class?.startsWith("M") ? "red" : "orange"}>{g.goes_class}</Pill></td><td className="mono">{hhmm(g.begin)}</td><td className="mono">{hhmm(g.peak)}</td><td className="mono">{hhmm(g.end)}</td></tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="text-sm text-muted">No flares listed ({data.summary.goes.status}).</p>
              )}
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
