import type * as echarts from "echarts";
import { useMemo, useState } from "react";
import type { ResultRow, Results } from "../api";
import { BASELINE, HEL1OS, MODEL, TARGET_LABEL, TARGET_SHORT, fmt, fmtPct } from "../api";
import Chart, { axisStyle } from "../components/Chart";
import { Card, ErrorBox, Loading, Notes, PageHeader, Pill, SourceNote } from "../components/ui";
import { useApi } from "../hooks";

const BASE_COLOR = BASELINE;

function bestBaseline(r: ResultRow): [string, { tss: number; ci95: [number, number] | null }] | null {
  const b = Object.entries(r.baselines).filter(([k]) => k !== "runner_up" && k !== "flux");
  if (!b.length) return null;
  return b.reduce((a, c) => (c[1].tss > a[1].tss ? c : a));
}

/** Bars (model vs best baseline) with 95 % interval whiskers drawn by a custom series. */
function tssChart(rows: Record<string, ResultRow>, order: string[]): echarts.EChartsOption {
  const cats = order.filter((t) => rows[t]);
  const model = cats.map((t) => rows[t].tss);
  const base = cats.map((t) => bestBaseline(rows[t])?.[1].tss ?? null);
  const whiskers = (offset: number, cis: ([number, number] | null)[]) => ({
    type: "custom" as const,
    name: offset < 0 ? "95% interval (model)" : "95% interval (baseline)",
    renderItem: (_p: unknown, api: echarts.CustomSeriesRenderItemAPI) => {
      const i = api.value(0) as number;
      const lo = api.coord([i, api.value(1)]);
      const hi = api.coord([i, api.value(2)]);
      const w = (api.size?.([1, 0]) as number[])[0] * 0.18;
      const x = lo[0] + offset * w * 1.2;
      const style = { stroke: "rgba(230,237,245,0.55)", lineWidth: 1.2 };
      return {
        type: "group" as const,
        children: [
          { type: "line" as const, shape: { x1: x, y1: lo[1], x2: x, y2: hi[1] }, style },
          { type: "line" as const, shape: { x1: x - 5, y1: lo[1], x2: x + 5, y2: lo[1] }, style },
          { type: "line" as const, shape: { x1: x - 5, y1: hi[1], x2: x + 5, y2: hi[1] }, style },
        ],
      };
    },
    data: cis.map((c, i) => (c ? [i, c[0], c[1]] : [i, null, null])),
    z: 10,
    tooltip: { show: false },
  });
  return {
    animation: false,
    tooltip: { trigger: "axis", valueFormatter: (v) => (typeof v === "number" ? v.toFixed(3) : String(v)) },
    legend: { top: 0, data: ["Champion model", "Best simple baseline"] },
    grid: { left: 44, right: 12, top: 40, bottom: 30 },
    xAxis: { type: "category", data: cats.map((t) => TARGET_SHORT[t] ?? t), ...axisStyle, axisLabel: { ...axisStyle.axisLabel, interval: 0, fontSize: 11 } },
    yAxis: { type: "value", name: "TSS", min: -0.2, max: 1, ...axisStyle },
    series: [
      { name: "Champion model", type: "bar", data: model, itemStyle: { color: MODEL, borderRadius: [3, 3, 0, 0] }, barGap: "20%", barWidth: "28%" },
      { name: "Best simple baseline", type: "bar", data: base, itemStyle: { color: BASE_COLOR, borderRadius: [3, 3, 0, 0] }, barWidth: "28%" },
      whiskers(-1, cats.map((t) => rows[t].ci95)),
      whiskers(1, cats.map((t) => bestBaseline(rows[t])?.[1].ci95 ?? null)),
    ],
  };
}

function monthChart(r: Results, target: string): echarts.EChartsOption {
  const pm = r.test.targets[target]?.per_month ?? {};
  const months = Object.keys(pm);
  const line = (key: string, name: string, color: string): echarts.SeriesOption => ({
    name, type: "line", data: months.map((m) => pm[m]?.[key] ?? null), symbolSize: 7, lineStyle: { color, width: 2 }, itemStyle: { color },
  });
  const h2 = r.holdout2.targets[target]?.per_month ?? {};
  return {
    animation: false,
    tooltip: { trigger: "axis", valueFormatter: (v) => (typeof v === "number" ? v.toFixed(3) : String(v)) },
    legend: { top: 0 },
    grid: { left: 48, right: 12, top: 36, bottom: 30 },
    xAxis: { type: "category", data: [...months, ...Object.keys(h2).map((m) => `${m} (h2)`)], ...axisStyle },
    yAxis: { type: "value", name: "TSS", min: -0.4, max: 1, ...axisStyle },
    series: [
      { ...line("chosen", "Champion (test)", MODEL), data: [...months.map((m) => pm[m]?.chosen ?? null), ...Object.keys(h2).map(() => null)] } as echarts.SeriesOption,
      { ...line("rule", "1-feature rule (test)", "#94a3b8"), data: [...months.map((m) => pm[m]?.rule ?? null), ...Object.keys(h2).map(() => null)] } as echarts.SeriesOption,
      { ...line("persistence", "Persistence (test)", "#64748b"), data: [...months.map((m) => pm[m]?.persistence ?? null), ...Object.keys(h2).map(() => null)] } as echarts.SeriesOption,
      {
        name: "Champion recipe (holdout2)",
        type: "scatter",
        symbolSize: 11,
        itemStyle: { color: HEL1OS },
        data: [...months.map(() => null), ...Object.values(h2).map((v) => (v.positives ? v.tss : null))],
      },
    ],
  };
}

function Table({ rows, order, holdout }: { rows: Record<string, ResultRow>; order: string[]; holdout?: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className="tbl">
        <thead>
          <tr>
            <th>Target</th><th>TSS [95%]</th><th>Quiet-start</th>
            {holdout ? <><th>Active / quiet days</th></> : <th>POD / FAR</th>}
            <th>Best baseline</th>{!holdout && <th>p vs baseline</th>}
          </tr>
        </thead>
        <tbody>
          {order.filter((t) => rows[t]).map((t) => {
            const r = rows[t];
            const bb = bestBaseline(r);
            return (
              <tr key={t} className={r.underpowered ? "text-dim" : ""}>
                <td>{TARGET_LABEL[t] ?? t} {r.underpowered && <Pill tone="amber">underpowered</Pill>}</td>
                <td className="mono"><b>{fmt(r.tss)}</b> {r.ci95 ? `[${fmt(r.ci95[0], 2)}, ${fmt(r.ci95[1], 2)}]` : ""}</td>
                <td className="mono">{fmt(r.tss_quiet_start)}</td>
                {holdout ? <td className="mono">{fmt(r.tss_active_days)} / {fmt(r.tss_quiet_days)}</td> : <td className="mono">{fmtPct(r.pod)} / {fmtPct(r.far)}</td>}
                <td className="mono">{bb ? `${bb[0]} ${fmt(bb[1].tss)}` : "–"}</td>
                {!holdout && <td className="mono">{r.paired_p ? Object.entries(r.paired_p).filter(([k]) => !k.includes("runner")).map(([, v]) => (v <= 0.0011 ? "≤ 0.001" : v.toFixed(2))).join(", ") : "–"}</td>}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function Performance() {
  const { data, error, loading, reload } = useApi<Results>("/results");
  const [target, setTarget] = useState("m_60m");
  const testOrder = ["now", "c_30m", "c_60m", "m_30m", "m_60m"];
  const h2Order = ["now", "c_30m", "c_60m", "c_120m", "m_30m", "m_60m", "m_120m"];
  const testOpt = useMemo(() => (data ? tssChart(data.test.targets, testOrder) : null), [data]); // eslint-disable-line react-hooks/exhaustive-deps
  const h2Opt = useMemo(() => (data ? tssChart(data.holdout2.targets, h2Order) : null), [data]); // eslint-disable-line react-hooks/exhaustive-deps
  const mOpt = useMemo(() => (data ? monthChart(data, target) : null), [data, target]);

  return (
    <div className="space-y-4">
      <PageHeader eyebrow="Evidence · frozen results" title="Performance" sub="Each held-out period scored exactly once. TSS: 0 = no skill, 1 = perfect." />
      {error && <ErrorBox error={error} onRetry={reload} />}
      {loading && <Loading height={360} />}
      {data && testOpt && h2Opt && mOpt && (
        <>
          <div className="grid gap-4 xl:grid-cols-2">
            <Card title={`Test · ${data.test.period[0].slice(0, 10)} → ${data.test.period[1].slice(0, 10)}`} right={<span className="text-dim">{data.test.days} days</span>}>
              <Chart option={testOpt} height={330} />
              <SourceNote>{data.test.source}</SourceNote>
            </Card>
            <Card title={`Holdout2 · ${data.holdout2.days} days`} right={data.holdout2.underpowered_m ? <Pill tone="amber">M underpowered · {data.holdout2.m_flares} flares</Pill> : null}>
              <Chart option={h2Opt} height={330} />
              <SourceNote>{data.holdout2.source}</SourceNote>
            </Card>
          </div>
          <Card
            title="Skill month by month"
            right={
              <select value={target} onChange={(e) => setTarget(e.target.value)} className="rounded-lg border border-white/10 bg-ink-800 px-2.5 py-1 font-sans text-xs normal-case tracking-normal text-fg">
                {testOrder.map((t) => <option key={t} value={t}>{TARGET_LABEL[t]}</option>)}
              </select>
            }
          >
            <Chart option={mOpt} height={300} />
            <SourceNote>Periwinkle dots: holdout2 months.</SourceNote>
          </Card>
          <div className="grid gap-4 xl:grid-cols-2">
            <Card title="Test period details"><Table rows={data.test.targets} order={testOrder} /></Card>
            <Card title="Holdout2 details"><Table rows={data.holdout2.targets} order={h2Order} holdout /></Card>
          </div>
          <Notes title="Read before quoting a number">
            <ul className="list-disc space-y-1 pl-5 marker:text-accent">
              {data.notes.map((n) => <li key={n}>{n}</li>)}
              <li>M-flare models mostly recognise active periods: early warnings, many false alarms.</li>
              <li>On holdout2 the C-flare models roughly match the current-flux baseline.</li>
            </ul>
          </Notes>
        </>
      )}
    </div>
  );
}
