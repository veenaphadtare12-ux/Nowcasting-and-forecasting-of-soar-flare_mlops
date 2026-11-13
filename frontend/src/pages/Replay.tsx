import type * as echarts from "echarts";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { DayInfo, DetectorEvent, Frame, GoesFlare, ReplayDay, StreamMeta } from "../api";
import { API, HEL1OS, SOLEXS, TARGETS, TARGET_COLOR, TARGET_LABEL, fmtPct, getJson, hhmm } from "../api";
import Chart, { axisStyle } from "../components/Chart";
import { Card, ErrorBox, Gauge, Loading, PageHeader, Pill } from "../components/ui";
import { useApi } from "../hooks";

type Buf = {
  t: string[];
  solexs: (number | null)[];
  czt: (number | null)[];
  cdte: (number | null)[];
  p: Record<string, (number | null)[]>;
  goes: GoesFlare[];
  det: DetectorEvent[];
};
type LogItem = { t: string; kind: "alert" | "clear" | "goes" | "trigger"; text: string };
const SPEEDS = [
  { speed: 60, step: 1, label: "60×" },
  { speed: 300, step: 5, label: "300×" },
  { speed: 600, step: 10, label: "600×" },
];
const empty = (): Buf => ({ t: [], solexs: [], czt: [], cdte: [], p: Object.fromEntries(TARGETS.map((x) => [x, []])), goes: [], det: [] });
const iso = (d: Date) => d.toISOString().slice(0, 19) + "Z";

export default function Replay() {
  const days = useApi<DayInfo[]>("/replay/days");
  const [day, setDay] = useState<string | null>(null);
  const [speedIx, setSpeedIx] = useState(1);
  const [playing, setPlaying] = useState(false);
  const [clock, setClock] = useState<string | null>(null);
  const [meta, setMeta] = useState<StreamMeta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [prefilling, setPrefilling] = useState(false);
  const [version, setVersion] = useState(0);
  const [log, setLog] = useState<LogItem[]>([]);
  const buf = useRef<Buf>(empty());
  const es = useRef<EventSource | null>(null);
  const lastAlerts = useRef<Record<string, boolean>>({});
  const raf = useRef<number | null>(null);

  const info = days.data?.find((d) => d.day === day) ?? null;
  useEffect(() => {
    if (!day && days.data?.length) setDay(days.data[0].day);
  }, [days.data, day]);

  const bump = useCallback(() => {
    if (raf.current != null) return;
    raf.current = requestAnimationFrame(() => {
      raf.current = null;
      setVersion((v) => v + 1);
    });
  }, []);

  const stop = useCallback(() => {
    es.current?.close();
    es.current = null;
    setPlaying(false);
  }, []);

  const noteEvents = useCallback((f: { t: string; alerts: Record<string, boolean>; goes: GoesFlare[]; det: DetectorEvent[] }, b: Buf) => {
    const items: LogItem[] = [];
    for (const [k, on] of Object.entries(f.alerts)) {
      if (on && !lastAlerts.current[k]) items.push({ t: f.t, kind: "alert", text: `ALERT ${TARGET_LABEL[k] ?? k}` });
      if (!on && lastAlerts.current[k]) items.push({ t: f.t, kind: "clear", text: `cleared ${TARGET_LABEL[k] ?? k}` });
    }
    lastAlerts.current = f.alerts;
    if (f.goes.length > b.goes.length) f.goes.slice(b.goes.length).forEach((g) => items.push({ t: g.begin.slice(0, 19) + "Z", kind: "goes", text: "GOES flare begins" }));
    f.goes.forEach((g, i) => {
      const old = b.goes[i];
      if (old && !old.goes_class && g.goes_class) items.push({ t: f.t, kind: "goes", text: `GOES flare peaked: ${g.goes_class}` });
    });
    if (f.det.length > b.det.length) items.push({ t: f.t, kind: "trigger", text: "SoLEXS detector trigger" });
    if (items.length) setLog((l) => [...items.reverse(), ...l].slice(0, 60));
  }, []);

  /** Load everything known up to `until` (history before the stream starts). */
  const prefill = useCallback(
    async (d: string, until: string) => {
      setPrefilling(true);
      setError(null);
      try {
        const r = await getJson<ReplayDay>(`/replay/${d}?until=${encodeURIComponent(until)}`);
        const b = empty();
        b.t = r.lightcurve.time;
        b.solexs = r.lightcurve.solexs_rate;
        b.czt = r.lightcurve.hx_czt_lo ?? r.lightcurve.time.map(() => null);
        b.cdte = r.lightcurve.hx_cdte_lo ?? r.lightcurve.time.map(() => null);
        const idx = new Map(b.t.map((x, i) => [x, i]));
        for (const k of TARGETS) {
          const arr: (number | null)[] = b.t.map(() => null);
          const s = r.predictions[k];
          s?.time.forEach((x, i) => {
            const j = idx.get(x);
            if (j != null) arr[j] = s.p_flare[i];
          });
          b.p[k] = arr;
        }
        b.goes = r.goes_flares;
        b.det = r.detector_events;
        buf.current = b;
        const thr = Object.fromEntries(Object.entries(r.predictions).map(([k, s]) => [k, s.threshold]));
        setMeta({ day: d, source: r.source, thresholds: thr, speed: SPEEDS[speedIx].speed, frames: 0 });
        lastAlerts.current = Object.fromEntries(TARGETS.map((k) => [k, (b.p[k].at(-1) ?? 0) >= (thr[k] ?? 1)]));
        setClock(until);
        bump();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setPrefilling(false);
      }
    },
    [bump, speedIx],
  );

  const play = useCallback(() => {
    if (!day) return;
    es.current?.close();
    const { speed, step } = SPEEDS[speedIx];
    const start = clock ?? `${day}T00:00:00Z`;
    const src = new EventSource(`${API}/replay/${day}/stream?speed=${speed}&step=${step}&start=${encodeURIComponent(start)}`);
    es.current = src;
    setPlaying(true);
    setError(null);
    src.addEventListener("meta", (e) => {
      const m = JSON.parse((e as MessageEvent).data) as StreamMeta;
      setMeta((old) => ({ ...m, thresholds: { ...(old?.thresholds ?? {}), ...m.thresholds } }));
    });
    src.addEventListener("frame", (e) => {
      const f = JSON.parse((e as MessageEvent).data) as Frame;
      const b = buf.current;
      noteEvents({ t: f.t, alerts: f.alerts, goes: f.goes, det: f.detector_events }, b);
      b.t.push(f.t);
      b.solexs.push(f.solexs_rate);
      b.czt.push(f.hx_czt_lo);
      b.cdte.push(f.hx_cdte_lo);
      for (const k of TARGETS) b.p[k].push(f.p[k] ?? null);
      b.goes = f.goes;
      b.det = f.detector_events;
      setClock(f.t);
      bump();
    });
    src.addEventListener("end", () => stop());
    src.onerror = () => {
      if (es.current === src) {
        setError("The replay stream was interrupted (is the API running?).");
        stop();
      }
    };
  }, [day, speedIx, clock, bump, noteEvents, stop]);

  // switching day: stop, clear, show the day from its start
  useEffect(() => {
    stop();
    buf.current = empty();
    setLog([]);
    lastAlerts.current = {};
    setMeta(null);
    if (day) void prefill(day, `${day}T00:00:00Z`);
  }, [day, stop, prefill]);
  useEffect(() => () => es.current?.close(), []);

  const seek = (minutes: number) => {
    if (!day) return;
    const wasPlaying = playing;
    stop();
    setLog([]);
    void prefill(day, iso(new Date(new Date(`${day}T00:00:00Z`).getTime() + minutes * 60000))).then(() => {
      if (wasPlaying) setTimeout(() => setPlaying(true), 0);
    });
  };
  useEffect(() => {
    // resume after a seek when the user was playing
    if (playing && !es.current && !prefilling) play();
  }, [playing, prefilling, play]);

  const b = buf.current;
  const thr = meta?.thresholds ?? {};
  const lastI = b.t.length - 1;
  const current = Object.fromEntries(TARGETS.map((k) => [k, lastI >= 0 ? b.p[k][lastI] : null]));
  const activeAlerts = TARGETS.filter((k) => current[k] != null && thr[k] != null && (current[k] as number) >= thr[k]);
  const minutes = clock && day ? Math.round((new Date(clock).getTime() - new Date(`${day}T00:00:00Z`).getTime()) / 60000) : 0;

  const option = useMemo<echarts.EChartsOption | null>(() => {
    if (!day) return null;
    const x0 = `${day}T00:00:00Z`;
    const x1 = iso(new Date(new Date(x0).getTime() + 86400000));
    const pts = (ys: (number | null)[]) => b.t.map((t, i) => [t, ys[i] != null && (ys[i] as number) > 0 ? ys[i] : null]);
    const areas = b.goes.map((g) => [
      { xAxis: g.begin, name: g.goes_class ?? "…", itemStyle: { color: g.goes_class?.match(/^[MX]/) ? "rgba(255,107,107,0.13)" : "rgba(245,181,68,0.09)" } },
      { xAxis: g.end ?? clock ?? g.begin },
    ]);
    const xAxis = (gi: number, show: boolean) => ({ type: "time" as const, gridIndex: gi, min: x0, max: x1, ...axisStyle, axisLabel: { ...axisStyle.axisLabel, show } });
    const hasHx = b.czt.some((v) => v != null) || b.cdte.some((v) => v != null) || info?.hel1os;
    const alertRows: echarts.SeriesOption[] = TARGETS.map((k, j) => ({
      name: `alert ${k}`,
      type: "scatter",
      xAxisIndex: 3,
      yAxisIndex: 3,
      symbol: "rect",
      symbolSize: [3, 9],
      itemStyle: { color: TARGET_COLOR[k] },
      data: b.t.flatMap((t, i) => ((b.p[k][i] ?? -1) >= (thr[k] ?? 2) ? [[t, j]] : [])),
      large: true,
    }));
    return {
      animation: false,
      tooltip: { trigger: "axis", axisPointer: { type: "line" }, valueFormatter: (v) => (typeof v === "number" ? v.toPrecision(3) : String(v)) },
      axisPointer: { link: [{ xAxisIndex: "all" }] },
      legend: { top: 0, data: ["SoLEXS soft X-rays", "HEL1OS CZT 20–40 keV", "HEL1OS CdTe 5–20 keV", ...TARGETS.map((k) => TARGET_LABEL[k])] },
      grid: [
        { left: 64, right: 18, top: 72, height: "23%" },
        { left: 64, right: 18, top: "36%", height: "16%" },
        { left: 64, right: 18, top: "56%", height: "22%" },
        { left: 64, right: 18, top: "82%", height: "12%" },
      ],
      xAxis: [xAxis(0, false), xAxis(1, false), xAxis(2, false), xAxis(3, true)],
      yAxis: [
        { type: "log", gridIndex: 0, name: "SoLEXS c/s", ...axisStyle },
        { type: "log", gridIndex: 1, name: "HEL1OS c/s", ...axisStyle, show: Boolean(hasHx) },
        { type: "value", gridIndex: 2, min: 0, max: 1, name: "P(flare)", ...axisStyle },
        { type: "category", gridIndex: 3, data: TARGETS.map((k) => k), ...axisStyle, axisLabel: { ...axisStyle.axisLabel, fontSize: 10 } },
      ],
      graphic: hasHx ? [] : [{ type: "text", left: "center", top: "43%", style: { text: "No HEL1OS session on this day", fill: "#5b6779", fontSize: 12 } }],
      series: [
        { name: "SoLEXS soft X-rays", type: "line", data: pts(b.solexs), showSymbol: false, lineStyle: { width: 1.2, color: SOLEXS }, itemStyle: { color: SOLEXS }, markArea: { silent: true, label: { color: "#ff8a7a", fontSize: 10 }, data: areas as never } },
        { name: "HEL1OS CZT 20–40 keV", type: "line", xAxisIndex: 1, yAxisIndex: 1, data: pts(b.czt), showSymbol: false, lineStyle: { width: 1, color: HEL1OS }, itemStyle: { color: HEL1OS } },
        { name: "HEL1OS CdTe 5–20 keV", type: "line", xAxisIndex: 1, yAxisIndex: 1, data: pts(b.cdte), showSymbol: false, lineStyle: { width: 1, color: "#c4b5fd" }, itemStyle: { color: "#c4b5fd" } },
        ...TARGETS.map(
          (k): echarts.SeriesOption => ({
            name: TARGET_LABEL[k],
            type: "line",
            xAxisIndex: 2,
            yAxisIndex: 2,
            data: b.t.map((t, i) => [t, b.p[k][i]]),
            showSymbol: false,
            lineStyle: { width: 1.1, color: TARGET_COLOR[k] },
            itemStyle: { color: TARGET_COLOR[k] },
          }),
        ),
        ...alertRows,
      ],
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version, day, clock, info?.hel1os]);

  return (
    <div className="space-y-4">
      <PageHeader
        eyebrow="Monitor · replay"
        title="Replay"
        sub="Past days, minute by minute, with only the data known at each moment."
        right={
          <div className="rounded-xl border border-white/[0.07] bg-ink-900/70 px-4 py-2.5 text-right">
            <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-dim">UTC · {day ?? "—"}</div>
            <div className="font-mono text-[28px] leading-tight text-fg tabular-nums" aria-live="polite">{clock ? clock.slice(11, 19) : "--:--:--"}</div>
          </div>
        }
      />

      {days.error && <ErrorBox error={days.error} onRetry={days.reload} />}
      {days.loading && <Loading height={80} />}
      {days.data && (
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
          {days.data.map((d) => (
            <button
              key={d.day}
              onClick={() => setDay(d.day)}
              className={`rounded-xl border p-3.5 text-left transition ${d.day === day ? "border-accent/50 bg-accent/[0.06] shadow-[0_0_0_1px_rgba(94,234,212,.15)]" : "border-white/[0.06] bg-ink-900/70 hover:border-white/15"}`}
            >
              <div className="font-mono text-[13px] text-fg tabular-nums">{d.day}</div>
              <div className="mt-2 flex min-h-5 flex-wrap gap-1">
                {d.goes_counts.X > 0 && <Pill tone="red">{d.goes_counts.X} X</Pill>}
                {d.goes_counts.M > 0 && <Pill tone="orange">{d.goes_counts.M} M</Pill>}
                {d.hel1os && <Pill tone="blue">HEL1OS</Pill>}
                {!d.goes_counts.X && !d.goes_counts.M && <Pill>quiet</Pill>}
              </div>
              <div className="mt-2 line-clamp-2 text-xs text-dim" title={d.note}>{d.note.split(":")[0]}</div>
            </button>
          ))}
        </div>
      )}

      {info && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
          <Pill tone="amber">demo, not evaluation</Pill>
          <span>{info.in_fit_period ? "inside the training period" : "threshold-selection month"}</span>
          <span className="text-dim">·</span>
          <span>source <span className="font-mono text-fg/80">{meta?.source ?? "…"}</span></span>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <button className="btn btn-primary" onClick={() => (playing ? stop() : play())} disabled={!day || prefilling}>
          {playing ? "❚❚ Pause" : "▶ Play"}
        </button>
        <button className="btn" onClick={() => seek(0)} disabled={!day || prefilling}>⟲ Restart</button>
        <div className="flex overflow-hidden rounded-lg border border-white/10" role="group" aria-label="speed">
          {SPEEDS.map((s, i) => (
            <button
              key={s.speed}
              className={`px-3 py-1.5 font-mono text-xs ${i === speedIx ? "bg-accent/15 text-accent" : "bg-ink-800 text-muted hover:bg-ink-700"}`}
              onClick={() => {
                setSpeedIx(i);
                if (playing) {
                  stop();
                  setTimeout(() => setPlaying(true), 0);
                }
              }}
            >
              {s.label}
            </button>
          ))}
        </div>
        <label className="ml-2 flex flex-1 items-center gap-2 text-xs text-muted">
          seek
          <input type="range" min={0} max={1439} step={10} value={minutes} onChange={(e) => seek(Number(e.target.value))} className="flex-1" disabled={!day} />
        </label>
      </div>

      {error && <ErrorBox error={error} />}

      <div
        className={`rounded-xl border px-4 py-3 transition ${activeAlerts.length ? "border-coral/40 bg-coral/[0.07]" : "border-accent/20 bg-accent/[0.035]"}`}
        role="status"
      >
        {activeAlerts.length ? (
          <div className="flex flex-wrap items-center gap-2 text-coral">
            <span className="font-mono text-xs font-medium uppercase tracking-[0.16em]">Alert</span>
            {activeAlerts.map((k) => (
              <span key={k} className="pill bg-coral/15 text-coral">
                {TARGET_LABEL[k]} · p {fmtPct(current[k], 0)} ≥ {fmtPct(thr[k], 0)}
              </span>
            ))}
          </div>
        ) : (
          <span className="flex items-center gap-2 font-mono text-xs text-accent"><i className="h-1.5 w-1.5 rounded-full bg-accent" />All clear · {clock ? hhmm(clock) : "–"} UTC</span>
        )}
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_320px]">
        <Card title="Light curves · probability · alerts">
          {option ? <Chart option={option} height={620} /> : <Loading height={620} />}
        </Card>
        <div className="space-y-4">
          <Card title="Probability now">
            <div className="space-y-2">
              {TARGETS.map((k) => (
                <Gauge key={k} target={k} p={current[k]} threshold={thr[k] ?? 1} color={TARGET_COLOR[k]} />
              ))}
            </div>
          </Card>
          <Card title="Event log">
            <ol className="max-h-72 space-y-1 overflow-y-auto pr-1 text-xs">
              {log.length === 0 && <li className="text-dim">Press Play to start the log.</li>}
              {log.map((l, i) => (
                <li key={`${l.t}-${i}`} className="flex gap-2">
                  <span className="mono text-dim">{hhmm(l.t)}</span>
                  <span className={l.kind === "alert" ? "text-coral" : l.kind === "clear" ? "text-accent" : l.kind === "goes" ? "text-amber" : "text-peri"}>{l.text}</span>
                </li>
              ))}
            </ol>
          </Card>
          <Card title="GOES flares">
            <ul className="space-y-1 text-xs">
              {b.goes.length === 0 && <li className="text-dim">None yet</li>}
              {b.goes.map((g, i) => (
                <li key={i} className="flex items-center justify-between">
                  <span className="mono text-muted">{hhmm(g.begin)}</span>
                  {g.goes_class ? <Pill tone={/^[MX]/.test(g.goes_class) ? "red" : "orange"}>{g.goes_class}</Pill> : <Pill tone="amber">rising…</Pill>}
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>
    </div>
  );
}
