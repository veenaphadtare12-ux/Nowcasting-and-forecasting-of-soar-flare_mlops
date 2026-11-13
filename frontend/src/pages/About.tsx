import { Card, PageHeader } from "../components/ui";

const FLOW = [
  ["Aditya-L1 SoLEXS + HEL1OS (ISRO)", "raw X-ray light curves"],
  ["Prefect daily_ingest", "schedule, retries, logs"],
  ["pandera data contracts", "a broken table stops the run"],
  ["pipeline feature code", "44 causal features every 10 s"],
  ["champion models (model bundle)", "from the MLflow registry"],
  ["predictions store", "Parquet + SQLite"],
  ["FastAPI", "/production, /replay, /results, /metrics"],
  ["this web app", "React + ECharts"],
];

export default function About() {
  return (
    <div className="max-w-5xl space-y-4">
      <PageHeader eyebrow="Project" title="About" sub="Solar-flare nowcasts and forecasts from Aditya-L1, end to end." />
      <Card title="The problem">
        <p className="max-w-3xl text-[15px] leading-relaxed text-fg/85">
          Every 10 seconds, <b className="font-medium text-amber">SoLEXS</b> soft X-rays (and <b className="font-medium text-peri">HEL1OS</b> hard X-rays
          when observing) answer five questions: is a flare happening now, and will a C- or M-class flare start within 30 or 60 minutes?
        </p>
      </Card>
      <Card title="How a prediction is made">
        <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {FLOW.map(([a, b], i) => (
            <li key={a} className="rounded-xl border border-white/[0.06] bg-ink-800/40 p-4 text-sm">
              <div className="text-xs text-dim">step {i + 1}</div>
              <div className="font-medium text-fg">{a}</div>
              <div className="text-xs text-muted">{b}</div>
            </li>
          ))}
        </ol>
      </Card>
      <Card title="Data">
        <ul className="list-disc space-y-1.5 pl-5 text-[14px] text-fg/80 marker:text-accent">
          <li>ISRO Aditya-L1 SoLEXS + HEL1OS level-1 data, 2025-04-09 … 2026-11-12.</li>
          <li>Labels from the NOAA SWPC GOES flare list.</li>
        </ul>
      </Card>
      <Card title="Limitations">
        <ul className="list-disc space-y-1.5 pl-5 text-[14px] text-fg/80 marker:text-accent">
          <li>Research and teaching system; NOAA SWPC issues official alerts.</li>
          <li>M-flare forecasts raise many false alarms: they mostly recognise active periods.</li>
          <li>Trained near solar maximum; drift is monitored for quieter years.</li>
        </ul>
      </Card>
    </div>
  );
}
