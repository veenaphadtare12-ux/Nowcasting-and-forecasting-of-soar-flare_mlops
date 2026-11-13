import { Card } from "../components/ui";

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
      <header>
        <h1 className="text-2xl font-semibold text-slate-100">About this project</h1>
        <p className="text-sm text-slate-400">An end-to-end MLOps project: nowcasting and short-term forecasting of solar flares from India's Aditya-L1 X-ray instruments.</p>
      </header>
      <Card title="The problem">
        <p className="text-sm leading-relaxed text-slate-300">
          Solar flares are sudden bursts of X-rays that can disturb radio communication and satellites. Aditya-L1 watches the Sun continuously from the
          L1 point. <b className="text-orange-300">SoLEXS</b> measures soft X-rays every second; <b className="text-blue-300">HEL1OS</b> measures
          hard X-rays (5–150 keV) during observing sessions. The models answer five questions every 10 seconds: is a flare happening now, and will a C-class
          or M-class flare start within the next 30 or 60 minutes?
        </p>
      </Card>
      <Card title="How a prediction is made">
        <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {FLOW.map(([a, b], i) => (
            <li key={a} className="rounded-lg border border-ink-700 bg-ink-800/50 p-3 text-sm">
              <div className="text-xs text-slate-500">step {i + 1}</div>
              <div className="font-medium text-slate-100">{a}</div>
              <div className="text-xs text-slate-400">{b}</div>
            </li>
          ))}
        </ol>
        <p className="mt-3 text-xs text-slate-500">
          Monitoring: the API exports Prometheus metrics (Grafana dashboard + alert rule) and Evidently checks feature drift every day. Everything runs in
          Docker Compose or Kubernetes from the same images, tagged with the git commit.
        </p>
      </Card>
      <Card title="Data">
        <ul className="list-disc space-y-1 pl-5 text-sm text-slate-300">
          <li>Aditya-L1 SoLEXS and HEL1OS level-1 data (ISRO), used from 2025-04-09 to 2026-11-12.</li>
          <li>Labels: the NOAA SWPC GOES flare list (begin, peak, end, class).</li>
          <li>Periods: tuning 2025-04-09 … 2026-01-31, validation … 2026-05-31, test … 2026-09-12 (scored once), holdout2 … 2026-11-12 (scored once).</li>
        </ul>
      </Card>
      <Card title="Limitations (read before using)">
        <ul className="list-disc space-y-1 pl-5 text-sm text-slate-300">
          <li>Not an operational warning service: NOAA SWPC issues official alerts. This is a research and teaching system.</li>
          <li>M-flare forecasts raise many false alarms (FAR above 0.9 at the TSS-optimal threshold): they mostly recognise active periods.</li>
          <li>Impulsive flares from a quiet background are often missed: nothing in the X-ray light curve precedes them.</li>
          <li>Trained near solar maximum; skill and calibration will change in quieter years, which is why drift is monitored.</li>
          <li>Holdout2 had only 7 M flares, so its M-flare results are underpowered and not used for any claim.</li>
        </ul>
      </Card>
    </div>
  );
}
