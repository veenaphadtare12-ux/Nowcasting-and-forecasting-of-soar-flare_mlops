"""The model bundle: the ONLY model/data source for the API, the containerised flows and Kubernetes.

    python -m src.serving.bundle export      # developer machine (needs mlflow.db + DVC data); writes model_bundle/
    python -m src.serving.bundle verify      # any machine: checks every file against manifest.json

Export reads the MLflow registry alias "champion" and the frozen result reports; it never retrains, re-tunes, re-scores
an evaluation period or reads holdout data. Replay days must lie in tune + val (checked).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from src import config
from src.ops.locks import check_window

SCHEMA_VERSION = 1
REGISTRY = {
    "now": "flare-nowcast",
    "c_30m": "flare-forecast-c30",
    "c_60m": "flare-forecast-c60",
    "m_30m": "flare-forecast-m30",
    "m_60m": "flare-forecast-m60",
}
DAYS = {  # tune + val only; chosen 2026-11-13 by GOES flare counts and SoLEXS coverage >= 95 % (docs/ARCHITECTURE.md)
    "2026-04-24": "X-class day: 2 X + 3 M flares, HEL1OS observing (inside the champions' fit period)",
    "2025-04-13": "Most active M day: 10 M flares, HEL1OS observing (inside the fit period)",
    "2025-11-04": "X-class day: 2 X + 2 M flares, no HEL1OS (inside the fit period)",
    "2026-05-16": "3 M flares in May 2026, the threshold month (not used for fitting)",
    "2026-02-21": "Quiet Sun: only 2 B flares (inside the fit period)",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=config.PROJECT_ROOT, text=True).strip()
    except Exception:
        return "unknown"


def clean(obj):
    """JSON-safe: non-finite floats (e.g. an unreachable FAR-capped threshold = inf) become null."""
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, (float, np.floating)):
        return float(obj) if np.isfinite(obj) else None
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    return obj


def _json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(obj), indent=1, default=str, allow_nan=False), encoding="utf-8", newline="\n")


# ---------------------------------------------------------------- export (developer machine)
def _export_models(out: Path, tracking_uri: str) -> dict:
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    import mlflow
    from mlflow import MlflowClient

    mlflow.set_tracking_uri(tracking_uri)
    client = MlflowClient(tracking_uri=tracking_uri)
    models = {}
    for target, name in REGISTRY.items():
        mv = client.get_model_version_by_alias(name, "champion")
        est = mlflow.sklearn.load_model(f"models:/{name}@champion")
        info = mlflow.models.get_model_info(f"models:/{name}@champion")
        feats = info.signature.inputs.input_names()
        path = out / "models" / f"{target}.joblib"
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(est, path, compress=3)
        try:
            ch = client.get_model_version_by_alias(name, "challenger")
            challenger = {"version": str(ch.version), "created": str(ch.creation_timestamp), "tags": dict(ch.tags)}
        except Exception:
            challenger = None
        t = dict(mv.tags)
        models[target] = {
            "registry_name": name,
            "version": str(mv.version),
            "run_id": mv.run_id,
            "alias": "champion",
            "learner": t.get("model"),
            "ideas": [x for x in (t.get("ideas") or "none").split(",") if x and x != "none"],
            "features": feats,
            "thresholds": {k: float(t[f"thr_{k}"]) for k in "ABC" if f"thr_{k}" in t},
            "fit_dates": t.get("fit_dates"),
            "threshold_block": t.get("threshold_block"),
            "test_tss_A": t.get("test_tss_A"),
            "trained_at_commit": t.get("git_commit"),
            "file": f"models/{target}.joblib",
            "sha256": sha256(path),
            "challenger": challenger,
        }
    return models


def _day_frames(day: pd.Timestamp, models: dict, chan_all: pd.DataFrame | None, base_tv: pd.DataFrame) -> dict:
    from src.final import features as ff
    from src.serving import features as sf

    proc = config.processed_dir()
    w = sf.warmup()
    cur = pd.read_parquet(proc / "solexs_clean" / f"{day:%Y%m%d}.parquet")["counts"]
    prev_f = proc / "solexs_clean" / f"{day - pd.Timedelta(days=1):%Y%m%d}.parquet"
    counts = cur
    if prev_f.exists():
        prev = pd.read_parquet(prev_f)["counts"]
        counts = pd.concat([prev[prev.index > day - w], cur])
    lo = day - w - pd.Timedelta(minutes=80)
    hc = None
    if chan_all is not None:
        hc = chan_all[(chan_all.index > lo) & (chan_all.index <= day + pd.Timedelta(days=1))]
    end = day + pd.Timedelta(days=1)
    pipe = base_tv[(base_tv.index > day) & (base_tv.index <= end)]
    per_target = {}
    for target, m in models.items():
        if m["ideas"]:
            ctx = base_tv[(base_tv.index > day - pd.Timedelta(days=8)) & (base_tv.index <= end)]
            fr, _ = ff.build(ctx, m["ideas"])
            per_target[target] = fr[(fr.index > day) & (fr.index <= end)][m["features"]].astype("float32")
    lc = pd.DataFrame({"solexs_rate": pipe["rate"]})
    if hc is not None and not hc.empty:
        b = hc.resample("10s", label="right", closed="right").mean()
        lc = lc.join(b[["cdte_lo", "czt_lo"]].rename(columns=lambda c: f"hx_{c}"), how="left")
    return {"counts": counts.astype("float32").to_frame("counts"), "hel": hc, "pipe": pipe, "per_target": per_target, "lc": lc}


def _predictions(day_frames: dict, models: dict, est: dict) -> pd.DataFrame:
    from src.validation import schemas as S

    rows = []
    for target, m in models.items():
        X = day_frames["per_target"].get(target, day_frames["pipe"])[m["features"]]
        p = est[target].predict_proba(X)[:, 1].astype(float)
        thr = m["thresholds"]["A"]
        rows.append(
            pd.DataFrame(
                {
                    "time": X.index,
                    "target": target,
                    "model": m["registry_name"],
                    "model_version": m["version"],
                    "p_flare": np.clip(p, 0, 1),
                    "threshold": thr,
                    "alert": p >= thr,
                }
            )
        )
    return S.validate(pd.concat(rows, ignore_index=True), S.PREDICTIONS, "bundle predictions")


def _events(day: pd.Timestamp) -> tuple[list, list]:
    proc = config.processed_dir()
    a, b = day, day + pd.Timedelta(days=1)
    g = pd.read_parquet(proc / "goes_matched.parquet")
    g = g[(g["end"] >= a) & (g["begin"] < b)].sort_values("begin")
    goes = [
        {"begin": r.begin, "peak": r.peak, "end": r.end, "goes_class": r.goes_class, "class_letter": r.class_letter}
        for r in g.itertuples()
    ]
    e = pd.read_parquet(proc / "events.parquet")
    e = e[(e["trigger_time"] >= a - pd.Timedelta(hours=3)) & (e["trigger_time"] < b)].sort_values("trigger_time")
    det = [
        {
            "trigger_time": r.trigger_time,
            "end_known_time": r.end_known_time,
            "onset": r.onset,
            "peak": r.peak,
            "end": r.end,
            "peak_counts_s": float(r.peak_counts_s),
            "goes_class": None if pd.isna(r.goes_class) else str(r.goes_class),
        }
        for r in e.itertuples()
    ]
    return goes, det


def _results() -> dict:
    R = config.PROJECT_ROOT / "reports"
    tm = json.loads((R / "final" / "test_metrics.json").read_text(encoding="utf-8"))
    san = json.loads((R / "final" / "sanity.json").read_text(encoding="utf-8"))
    h2 = json.loads((R / "holdout2" / "metrics.json").read_text(encoding="utf-8"))
    test = {}
    for t, r in tm["targets"].items():
        A = r["metrics"]["chosen"]["A"]
        test[t] = {
            "model": r["model"],
            "ideas": r["ideas"],
            "tss": A["all"]["tss"],
            "ci95": [A["all"]["ci_low"], A["all"]["ci_high"]],
            "tss_quiet_start": A["quiet"]["tss"],
            "pod": A["all"]["pod"],
            "far": A["all"]["far"],
            "hss": A["all"]["hss"],
            "baselines": {
                b: {
                    "tss": r["metrics"][b]["A"]["all"]["tss"],
                    "ci95": [r["metrics"][b]["A"]["all"]["ci_low"], r["metrics"][b]["A"]["all"]["ci_high"]],
                }
                for b in ("rule", "persistence", "runner_up")
            },
            "paired_p": {k: v["p_one_sided"] for k, v in r["paired"].items()},
            "per_month": {m: v for m, v in san["monthly"].get(t, {}).items() if m != "without_best_month"},
        }
    hold = {}
    for t, r in h2["forecasts"].items():
        a = r["aditya"]
        A = a["points"]["A"]
        hold[t] = {
            "tss": A["tss"],
            "ci95": A["ci95"],
            "tss_quiet_start": A["tss_quietstart"],
            "tss_active_days": A["tss_active_days"],
            "tss_quiet_days": A["tss_quiet_days"],
            "pod": A["pod_far"]["pod"],
            "far": A["pod_far"]["far"],
            "positives": a["positives"],
            "days": a["days"],
            "per_month": {
                m: {"tss": v["tss"], "positives": v["positives"], "rows": v["rows"]} for m, v in A["per_month"].items()
            },
            "baselines": {b: {"tss": v["tss"], "ci95": v.get("ci95")} for b, v in a.get("baselines", {}).items()},
            "underpowered": t.startswith("m_") and bool(h2.get("underpowered_m")),
            "with_goes_tss": r.get("with_goes", {}).get("points", {}).get("A", {}).get("tss"),
        }
    return {
        "test": {
            "period": tm["test_period"],
            "days": next(iter(tm["targets"].values()))["test_days"],
            "targets": test,
            "models": "FINAL_CHOICE.md champions (registry version 1)",
            "source": "reports/final/test_metrics.json, reports/final/sanity.json",
        },
        "holdout2": {
            "days": len(h2["days"]),
            "m_flares": h2["m_flares_on_usable_days"],
            "underpowered_m": h2["underpowered_m"],
            "targets": hold,
            "models": "FINAL_CHOICE_2.md refits (same recipes, trained to Aug 2026; not registered)",
            "source": "reports/holdout2/metrics.json",
        },
        "notes": [
            "Metric: TSS at operating point A (threshold that maximised TSS on the threshold month), 95 % day-bootstrap intervals.",
            "Holdout2 M-flare results are UNDERPOWERED (7 M flares): no claim is made from them.",
            "Test and holdout2 were each scored exactly once; nothing here is recomputed.",
        ],
    }


def _pipeline_status(models: dict) -> dict:
    import yaml

    st = yaml.safe_load((config.PROJECT_ROOT / "dvc.yaml").read_text(encoding="utf-8"))["stages"]
    stages = [
        {
            "name": n,
            "frozen": bool(s.get("frozen")),
            "deps": len(s.get("deps", [])),
            "outs": [o if isinstance(o, str) else next(iter(o)) for o in s.get("outs", [])],
        }
        for n, s in st.items()
    ]
    edges = []
    outs = {o: n for n, s in st.items() for o in (x if isinstance(x, str) else next(iter(x)) for x in s.get("outs", []))}
    for n, s in st.items():
        for d in s.get("deps", []):
            for o, src in outs.items():
                if d == o or d.startswith(o + "/"):
                    edges.append([src, n])
    runs_f = config.PROJECT_ROOT / "data" / "predictions" / "flow_runs.json"
    runs = json.loads(runs_f.read_text(encoding="utf-8")) if runs_f.exists() else {}
    return {
        "dvc": {
            "stages": stages,
            "edges": sorted(map(list, set(map(tuple, edges)))),
            "frozen": sum(s["frozen"] for s in stages),
            "total": len(stages),
        },
        "registry": {
            t: {"name": m["registry_name"], "champion": m["version"], "challenger": (m["challenger"] or {}).get("version")}
            for t, m in models.items()
        },
        "flow_runs": runs,
        "tools": [
            {"tool": "Git + GitHub", "status": "used"},
            {"tool": "DVC", "status": "used"},
            {"tool": "MLflow", "status": "used"},
            {"tool": "pandera", "status": "used"},
            {"tool": "Prefect", "status": "used"},
            {"tool": "Evidently", "status": "used"},
            {"tool": "pytest + ruff", "status": "used"},
            {"tool": "GitHub Actions", "status": "used"},
            {"tool": "FastAPI", "status": "used"},
            {"tool": "Docker / Compose", "status": "used"},
            {"tool": "Prometheus + Grafana", "status": "used"},
            {"tool": "Kubernetes (kind)", "status": "used"},
            {"tool": "Terraform (AWS)", "status": "prepared, not applied"},
        ],
    }


def _coverage() -> dict:
    """Daily SoLEXS valid fraction and monthly GOES flare counts over the development period only (no holdout)."""
    lo, hi = config.period_bounds("tune")[0], config.period_bounds("test")[1]
    qc = pd.read_csv(config.processed_dir() / "solexs_qc.csv")
    qc["date"] = pd.to_datetime(qc["date"], utc=True)
    qc = qc[(qc["date"] >= lo) & (qc["date"] < hi)]
    days = pd.date_range(lo, hi - pd.Timedelta(days=1), freq="D")
    vf = qc.set_index("date")["valid_fraction"].reindex(days).fillna(0.0)
    usable = qc.set_index("date")["usable"].astype(bool).reindex(days).fillna(False)
    g = pd.read_parquet(config.processed_dir() / "goes_matched.parquet")
    t = g["peak"].fillna(g["begin"])
    g = g[(t >= lo) & (t < hi)].assign(month=t.dt.strftime("%Y-%m"))
    monthly = g.groupby(["month", "class_letter"]).size().unstack(fill_value=0).reindex(columns=list("BCMX"), fill_value=0)
    periods = {
        p: [str(config.period_bounds(p)[0].date()), str((config.period_bounds(p)[1] - pd.Timedelta(days=1)).date())]
        for p in ("tune", "val", "test")
    }
    return {
        "days": [d.strftime("%Y-%m-%d") for d in days],
        "valid_fraction": [round(float(v), 4) for v in vf],
        "usable": [bool(u) for u in usable],
        "periods": periods,
        "goes_monthly": {m: {k: int(v) for k, v in r.items()} for m, r in monthly.iterrows()},
        "summary": {"days": len(days), "usable_days": int(usable.sum()), "mean_valid_fraction": round(float(vf.mean()), 4)},
        "note": "Development period only (tune, val and the old test period as development data); holdout data is never included.",
    }


def _drift_samples(out: Path, feats: list[str], n: int = 20000, seed: int = 0) -> None:
    """Feature samples for check_drift in containers: the champions' training block and the last 30 development days
    (development data only; no labels)."""
    from src.dev2 import protocol
    from src.ops.drift import default_windows

    d = protocol.load(feats)
    rng = np.random.default_rng(seed)
    w = default_windows()
    for name, (a, b) in (("reference_sample", w["reference"]), ("recent_dev_sample", w["current"])):
        x = d[(d.index >= a) & (d.index < b)]
        x = x.iloc[np.sort(rng.choice(len(x), min(n, len(x)), replace=False))]
        x.astype("float32").to_parquet(out / f"{name}.parquet", compression="zstd")


def export(out: Path | None = None, tracking_uri: str | None = None) -> dict:
    from src import features, hel1os
    from src.models.train import load_period

    out = Path(out) if out else config.PROJECT_ROOT / "model_bundle"
    tmp = out.with_name(out.name + "_tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    for d in DAYS:  # replay days: tune + val only (scorable window), never holdout or the old test
        check_window(pd.Timestamp(d, tz="UTC"), pd.Timestamp(d, tz="UTC") + pd.Timedelta(days=1), kind="score")
    models = _export_models(tmp, tracking_uri or config.mlflow_uri())
    est = {t: joblib.load(tmp / m["file"]) for t, m in models.items()}
    hel = hel1os.load_optional()
    chan_all = features.hel1os_channels(hel) if hel is not None and not hel.empty else None
    base_tv = pd.concat([load_period(p) for p in ("tune", "val")]).sort_index()  # load_period refuses the test period
    days = {}
    for d, note in DAYS.items():
        day = pd.Timestamp(d, tz="UTC")
        fr = _day_frames(day, models, chan_all, base_tv)
        ddir = tmp / "replay" / d
        ddir.mkdir(parents=True)
        fr["counts"].to_parquet(ddir / "inputs_solexs_1s.parquet", compression="zstd")
        if fr["hel"] is not None and not fr["hel"].empty:
            fr["hel"].astype("float32").to_parquet(ddir / "inputs_hel1os_1s.parquet", compression="zstd")
        feats = list(models["now"]["features"])
        fr["pipe"][feats + ["flare_in_progress_at_t"]].to_parquet(ddir / "features_pipeline.parquet", compression="zstd")
        for t, f in fr["per_target"].items():
            f.to_parquet(ddir / f"features_{t}.parquet", compression="zstd")
        fr["lc"].astype("float32").to_parquet(ddir / "lightcurve.parquet", compression="zstd")
        pred = _predictions(fr, models, est)
        pred.to_parquet(ddir / "predictions.parquet", compression="zstd")
        goes, det = _events(day)
        _json(ddir / "goes_flares.json", goes)
        _json(ddir / "detector_events.json", det)
        cls = pd.Series([g["class_letter"] for g in goes]).value_counts().reindex(list("BCMX"), fill_value=0)
        days[d] = {
            "note": note,
            "goes_counts": {k: int(v) for k, v in cls.items()},
            "hel1os": fr["hel"] is not None and not fr["hel"].empty,
            "rows": int(len(fr["pipe"])),
            "in_fit_period": day < pd.Timestamp(config.load_params()["final"]["fit_end"], tz="UTC"),
        }
    _json(tmp / "model_card.json", _results())
    (tmp / "drift").mkdir()
    drift = config.PROJECT_ROOT / "reports" / "drift" / "latest.json"
    if drift.exists():
        shutil.copy(drift, tmp / "drift" / "latest.json")
    _drift_samples(tmp / "drift", models["now"]["features"])
    _json(tmp / "pipeline" / "status.json", _pipeline_status(models))
    _json(tmp / "data" / "coverage.json", _coverage())
    files = {p.relative_to(tmp).as_posix(): sha256(p) for p in sorted(tmp.rglob("*")) if p.is_file()}
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "bundle_version": datetime.now(timezone.utc).strftime("%Y.%m.%d-%H%M"),
        "git_sha": _git_sha(),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "MLflow registry alias 'champion' (mlflow.db) + frozen reports",
        "models": models,
        "days": days,
        "files": files,
    }
    _json(tmp / "manifest.json", manifest)
    if out.exists():
        shutil.rmtree(out)
    tmp.rename(out)
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(f"bundle {manifest['bundle_version']} -> {out}  ({size / 1e6:.1f} MB, {len(files) + 1} files)")
    return manifest


# ---------------------------------------------------------------- load (any machine)
class Bundle:
    """Read-only view of a model bundle. Every model file is verified against its SHA-256 before it is loaded."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.manifest = json.loads((self.path / "manifest.json").read_text(encoding="utf-8"))
        self._models: dict = {}

    @property
    def version(self) -> str:
        return self.manifest["bundle_version"]

    @property
    def days(self) -> dict:
        return self.manifest["days"]

    def model_meta(self, target: str) -> dict:
        return self.manifest["models"][target]

    def model(self, target: str):
        if target not in self._models:
            m = self.model_meta(target)
            p = self.path / m["file"]
            if sha256(p) != m["sha256"]:
                raise RuntimeError(f"bundle model {p.name} does not match its SHA-256 in manifest.json")
            self._models[target] = joblib.load(p)
        return self._models[target]

    def verify(self) -> list[str]:
        bad = [rel for rel, h in self.manifest["files"].items() if not (self.path / rel).exists() or sha256(self.path / rel) != h]
        return bad

    def json(self, rel: str):
        return json.loads((self.path / rel).read_text(encoding="utf-8"))

    def day_dir(self, day: str) -> Path:
        if day not in self.days:
            raise KeyError(day)
        return self.path / "replay" / day

    def table(self, day: str, name: str) -> pd.DataFrame | None:
        p = self.day_dir(day) / f"{name}.parquet"
        return pd.read_parquet(p) if p.exists() else None

    def model_input(self, day: str, target: str) -> pd.DataFrame:
        f = self.table(day, f"features_{target}")
        if f is None:
            f = self.table(day, "features_pipeline")
        return f[self.model_meta(target)["features"]]


@lru_cache(maxsize=4)
def load(path: str | None = None) -> Bundle:
    from src.settings import get_settings

    return Bundle(Path(path) if path else get_settings().bundle_dir)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "verify"
    if cmd == "export":
        export()
    else:
        bad = load().verify()
        print("bundle OK" if not bad else f"bundle files changed: {bad}")
        sys.exit(1 if bad else 0)
