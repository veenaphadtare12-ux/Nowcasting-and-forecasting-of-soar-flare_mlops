// Typed client for the FastAPI service. Everything goes through /api (nginx in the container, Vite proxy in dev).
export const API = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api";

export const TARGETS = ["now", "c_30m", "c_60m", "m_30m", "m_60m"] as const;
export type Target = (typeof TARGETS)[number];
export const TARGET_LABEL: Record<string, string> = {
  now: "Flare now (nowcast)",
  c_30m: "≥C flare in 30 min",
  c_60m: "≥C flare in 60 min",
  c_120m: "≥C flare in 120 min",
  m_30m: "≥M flare in 30 min",
  m_60m: "≥M flare in 60 min",
  m_120m: "≥M flare in 120 min",
};
export const TARGET_SHORT: Record<string, string> = {
  now: "Nowcast",
  c_30m: "≥C 30m",
  c_60m: "≥C 60m",
  c_120m: "≥C 2h",
  m_30m: "≥M 30m",
  m_60m: "≥M 60m",
  m_120m: "≥M 2h",
};
export const SOLEXS = "#F5B544"; // soft X-rays: amber
export const HEL1OS = "#8EA2FF"; // hard X-rays: periwinkle
export const MODEL = "#5EEAD4"; // champion models: signal mint
export const BASELINE = "#3B4658";
export const ALERT = "#FF6B6B";
export const TARGET_COLOR: Record<string, string> = {
  now: "#5EEAD4",
  c_30m: "#F7D070",
  c_60m: "#F5A54A",
  m_30m: "#FF8A7A",
  m_60m: "#F0627E",
};

export type Nullable<T> = T | null;
export type Health = {
  status: "ok";
  bundle_version: string;
  bundle_git_sha: string;
  image_git_sha: string;
  environment: string;
  models_loaded: string[];
  replay_days: number;
};
export type ModelInfo = {
  target: string;
  registry_name: string;
  version: string;
  alias: string;
  learner: string | null;
  ideas: string[];
  n_features: number;
  features: string[];
  thresholds: { A: Nullable<number>; B: Nullable<number>; C: Nullable<number> };
  fit_dates: string | null;
  threshold_block: string | null;
  test_tss_A: string | null;
  inputs: "Aditya-only" | "includes GOES XRS";
  challenger: Nullable<{ version: string }>;
};
export type DayInfo = {
  day: string;
  note: string;
  goes_counts: Record<string, number>;
  hel1os: boolean;
  rows: number;
  in_fit_period: boolean;
};
export type Series = {
  model: string;
  model_version: string;
  threshold: number;
  time: string[];
  p_flare: Nullable<number>[];
  alert: boolean[];
};
export type GoesFlare = {
  begin: string;
  peak: Nullable<string>;
  end: Nullable<string>;
  goes_class: Nullable<string>;
  class_letter?: Nullable<string>;
  in_progress?: boolean;
};
export type DetectorEvent = {
  trigger_time: string;
  ended: boolean;
  onset: Nullable<string>;
  peak: Nullable<string>;
  end: Nullable<string>;
  peak_counts_s: Nullable<number>;
  goes_class: Nullable<string>;
};
export type LightCurve = {
  time: string[];
  solexs_rate: Nullable<number>[];
  hx_czt_lo?: Nullable<number>[];
  hx_cdte_lo?: Nullable<number>[];
};
export type ReplayDay = {
  day: string;
  until: string;
  note: string;
  in_fit_period: boolean;
  source: "store" | "bundle";
  run: Record<string, unknown>;
  lightcurve: LightCurve;
  predictions: Record<string, Series>;
  goes_flares: GoesFlare[];
  detector_events: DetectorEvent[];
};
export type Frame = {
  t: string;
  solexs_rate: Nullable<number>;
  hx_czt_lo: Nullable<number>;
  hx_cdte_lo: Nullable<number>;
  p: Record<string, Nullable<number>>;
  alerts: Record<string, boolean>;
  goes: GoesFlare[];
  detector_events: DetectorEvent[];
};
export type StreamMeta = { day: string; source: string; thresholds: Record<string, number>; speed: number; frames: number };

export type Freshness = {
  production_start: string;
  latest_available_day: Nullable<string>;
  latest_scored_day: Nullable<string>;
  pending_days: string[];
  scored_days: string[];
  hours_since_last_scoring: Nullable<number>;
  checked_at: string;
};
export type ProductionSummary = {
  day: string;
  scored_at: string;
  bundle_version: string;
  rows: number;
  valid_fraction: number;
  targets: Record<string, { model: string; threshold: number; alerts: number; alert_minutes: number; max_p: number; mean_p: number; first_alert: Nullable<string> }>;
  not_scored: Record<string, string>;
  goes: { status: string; flares: GoesFlare[] };
};
export type ProductionLatest =
  | { status: "no_data"; freshness: Freshness; message: string }
  | {
      status: "ok";
      freshness: Freshness;
      day: string;
      summary: ProductionSummary;
      lightcurve: LightCurve;
      predictions: Record<string, Series>;
      goes_flares: GoesFlare[];
    };

export type ResultRow = {
  tss: number;
  ci95: [number, number] | null;
  tss_quiet_start: number;
  pod: number;
  far: number;
  hss?: number;
  baselines: Record<string, { tss: number; ci95: [number, number] | null }>;
  paired_p?: Record<string, number>;
  per_month: Record<string, Record<string, number>>;
  underpowered?: boolean;
  tss_active_days?: number;
  tss_quiet_days?: number;
  positives?: number;
  model?: string;
  ideas?: string[];
};
export type Results = {
  test: { period: string[]; days: number; targets: Record<string, ResultRow>; models: string; source: string };
  holdout2: { days: number; m_flares: number; underpowered_m: boolean; targets: Record<string, ResultRow>; models: string; source: string };
  notes: string[];
};
export type Drift = {
  drifted_share: number;
  drift_flag: boolean;
  features_checked: number;
  drifted_features: string[];
  per_feature?: Record<string, { score: number; method: string; threshold: number; drifted: boolean }>;
  source?: string;
  mode?: string;
  current_label?: string;
  reference_label?: string;
  reference_window?: string[];
  current_window?: string[];
};
export type Coverage = {
  days: string[];
  valid_fraction: number[];
  usable: boolean[];
  periods: Record<string, [string, string]>;
  goes_monthly: Record<string, Record<string, number>>;
  summary: { days: number; usable_days: number; mean_valid_fraction: number };
  note: string;
};
export type PipelineStatus = {
  dvc: { stages: { name: string; frozen: boolean; deps: number; outs: string[] }[]; edges: [string, string][]; frozen: number; total: number };
  registry: Record<string, { name: string; champion: string; challenger: Nullable<string> }>;
  flow_runs: Record<string, { status: string; finished_at: string; info: Record<string, unknown> }>;
  tools: { tool: string; status: string }[];
  predictions_store: { exists: boolean; days: string[] };
  bundle: { version: string; git_sha: string; created_at: string };
  production: Freshness;
  prefect: {
    configured: boolean;
    reachable?: boolean;
    ui?: string;
    error?: string;
    deployments?: { name: string; schedules: Nullable<string>[] }[];
    recent_runs?: { flow: string; name: string; state: Nullable<string>; start: Nullable<string>; end: Nullable<string> }[];
  };
  mlflow: { configured: boolean; reachable?: boolean; ui?: string; models?: Record<string, { champion: Nullable<string>; challenger: Nullable<string> }> };
  drift: Drift;
};

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const r = await fetch(`${API}${path}`, { signal, headers: { Accept: "application/json" } });
  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`;
    try {
      const j = await r.json();
      if (j?.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* not JSON */
    }
    throw new Error(detail);
  }
  return (await r.json()) as T;
}

export const fmtPct = (x: Nullable<number> | undefined, d = 0) => (x == null ? "–" : `${(x * 100).toFixed(d)}%`);
export const fmt = (x: Nullable<number> | undefined, d = 3) => (x == null || Number.isNaN(x) ? "–" : x.toFixed(d));
export const hhmm = (iso: Nullable<string> | undefined) => (iso ? iso.slice(11, 16) : "–");
