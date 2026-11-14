// Load test for the flare API (k6). Run with scripts\loadtest.ps1 (Docker image grafana/k6, inside the Compose network).
//   BASE_URL   default http://frontend:8080/api  (through nginx, like a browser)
//   API_KEY    X-API-Key for POST /predict and the per-key rate-limit budget
//   VUS, DURATION   default 50 virtual users for 2 minutes
// The mix follows what the website does: health and model list, replay windows, results, plus some /predict calls.
// SLOs (docs/SLO.md) are encoded as thresholds: the run fails if p95 >= 300 ms or more than 1 % of requests fail.
import http from "k6/http";
import { check, sleep } from "k6";

const BASE = __ENV.BASE_URL || "http://frontend:8080/api";
const KEY = __ENV.API_KEY || "";
const HDR = { headers: { "X-API-Key": KEY } };

export const options = {
  scenarios: {
    website_mix: {
      executor: "constant-vus",
      vus: Number(__ENV.VUS || 50),
      duration: __ENV.DURATION || "2m",
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<300"],
  },
  summaryTrendStats: ["avg", "min", "med", "p(90)", "p(95)", "p(99)", "max"],
};

export function setup() {
  const models = http.get(`${BASE}/models`, HDR).json();
  const now = models.find((m) => m.target === "now");
  const row = {};
  for (const f of now.features) row[f] = 0.0;
  return { predictBody: JSON.stringify({ target: "now", rows: [row] }) };
}

export default function (data) {
  const predictBody = data.predictBody;
  const r = Math.random();
  let res;
  if (r < 0.25) {
    res = http.get(`${BASE}/health`, Object.assign({ tags: { name: "health" } }, HDR));
  } else if (r < 0.45) {
    res = http.get(`${BASE}/models`, Object.assign({ tags: { name: "models" } }, HDR));
  } else if (r < 0.6) {
    res = http.get(`${BASE}/replay/days`, Object.assign({ tags: { name: "replay_days" } }, HDR));
  } else if (r < 0.75) {
    const hour = String(6 + Math.floor(Math.random() * 12)).padStart(2, "0");
    res = http.get(`${BASE}/replay/2026-04-24?until=2026-04-24T${hour}:00:00Z&step=6`, Object.assign({ tags: { name: "replay_window" } }, HDR));
  } else if (r < 0.9) {
    res = http.get(`${BASE}/results`, Object.assign({ tags: { name: "results" } }, HDR));
  } else {
    res = http.post(`${BASE}/predict`, predictBody, {
      headers: { "X-API-Key": KEY, "Content-Type": "application/json" },
      tags: { name: "predict" },
    });
  }
  check(res, { "status 200": (x) => x.status === 200 });
  sleep(0.5 + Math.random());
}

export function handleSummary(data) {
  const m = data.metrics;
  const d = m.http_req_duration.values;
  const out = {
    vus: Number(__ENV.VUS || 50),
    duration: __ENV.DURATION || "2m",
    requests: m.http_reqs.values.count,
    rps: m.http_reqs.values.rate,
    error_rate: m.http_req_failed.values.rate,
    p50_ms: d.med,
    p95_ms: d["p(95)"],
    p99_ms: d["p(99)"],
    max_ms: d.max,
    slo_p95_lt_300ms: d["p(95)"] < 300,
    slo_errors_lt_1pct: m.http_req_failed.values.rate < 0.01,
  };
  return {
    "/results/summary.json": JSON.stringify(out, null, 2),
    stdout: JSON.stringify(out, null, 2) + "\n",
  };
}
