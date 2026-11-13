"""Production pipeline: score NEW days with the champion models (daily_ingest, docs/ARCHITECTURE.md section 4).

    new raw day -> pandera (raw counts) -> features (pipeline code) -> pandera (features) -> champions (model bundle)
    -> pandera (predictions) -> predictions store -> API /production/* -> frontend "Latest"

Production days start on FLARE_PRODUCTION_START (default 2026-11-13, the day after holdout2): holdout2 and every
evaluation period stay locked, so production only ever scores data never used before.

Sources of new days:
- raw SoLEXS L1 day folders (FITS) in FLARE_RAW_SOLEXS_DIR, cleaned with the pipeline's src/solexs.py (GTI, NaN rows);
- an inbox FLARE_INBOX_DIR/<YYYY-MM-DD>.parquet of cleaned 1-s counts (CI / end-to-end tests).
Only targets whose champion needs just the 44 base features are scored in production (now, c_60m, m_60m); the other
champions need long-context, spectral or GOES inputs that the production pipeline does not build yet (reported).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src.ops import replay
from src.serving import bundle as B
from src.serving import features as sf
from src.settings import get_settings
from src.validation import production as PV
from src.validation import schemas as S

log = logging.getLogger(__name__)
DAY_RE = re.compile(r"AL1_SLX_L1_(\d{8})_v")


def start() -> pd.Timestamp:
    return pd.Timestamp(get_settings().production_start, tz="UTC")


def prod_dir() -> Path:
    d = Path(get_settings().predictions_dir) / "production"
    d.mkdir(parents=True, exist_ok=True)
    return d


def base_targets(b: B.Bundle) -> list[str]:
    base = set(b.model_meta("now")["features"])
    return [t for t, m in b.manifest["models"].items() if set(m["features"]) <= base]


# ---------------------------------------------------------------- discovery
def available_days() -> dict[str, str]:
    """{YYYY-MM-DD: source} for production days with data (raw FITS folder or inbox parquet), oldest first."""
    s = get_settings()
    out: dict[str, str] = {}
    raw = Path(s.raw_solexs_dir) if s.raw_solexs_dir else None
    if raw and raw.exists():
        for p in raw.iterdir():
            m = DAY_RE.match(p.name)
            if m:
                out[pd.Timestamp(m.group(1)).strftime("%Y-%m-%d")] = "raw"
    inbox = Path(s.inbox_dir) if s.inbox_dir else None
    if inbox and inbox.exists():
        for p in inbox.glob("*.parquet"):
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem):
                out.setdefault(p.stem, "inbox")
    t0 = start()
    return {d: src for d, src in sorted(out.items()) if pd.Timestamp(d, tz="UTC") >= t0}


def scored_days() -> list[str]:
    return sorted(p.name.removesuffix(".json") for p in prod_dir().glob("????-??-??.json"))


def pending_days() -> list[str]:
    done = set(scored_days())
    return [d for d in available_days() if d not in done]


# ---------------------------------------------------------------- one day
def _day_counts(day: str, source: str) -> pd.Series:
    s = get_settings()
    if source == "inbox":
        return pd.read_parquet(Path(s.inbox_dir) / f"{day}.parquet")["counts"].astype("float64")
    from src import solexs

    for d in solexs.list_days(Path(s.raw_solexs_dir)):
        if d.date.strftime("%Y-%m-%d") == day and d.complete:
            return solexs.clean_day(d)[0]["counts"].astype("float64")
    raise FileNotFoundError(f"no complete SoLEXS L1 folder (light curve + GTI) for {day}")


def load_counts(day: str) -> pd.Series:
    """1-s counts of the day plus the previous day's warm-up tail (same rule as the dataset builder), if available."""
    avail = _all_days()
    cur = _day_counts(day, avail[day])
    prev = (pd.Timestamp(day) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    if prev in avail:
        p = _day_counts(prev, avail[prev])
        t = pd.Timestamp(day, tz="UTC")
        cur = pd.concat([p[p.index > t - sf.warmup()], cur])
    return cur


def _all_days() -> dict[str, str]:
    """Like available_days but without the production-start filter (warm-up may use the day before the start)."""
    s = get_settings()
    out: dict[str, str] = {}
    if s.raw_solexs_dir and Path(s.raw_solexs_dir).exists():
        for p in Path(s.raw_solexs_dir).iterdir():
            m = DAY_RE.match(p.name)
            if m:
                out[pd.Timestamp(m.group(1)).strftime("%Y-%m-%d")] = "raw"
    if s.inbox_dir and Path(s.inbox_dir).exists():
        for p in Path(s.inbox_dir).glob("????-??-??.parquet"):
            out.setdefault(p.stem, "inbox")
    t0 = start() - pd.Timedelta(days=1)
    return {d: v for d, v in out.items() if pd.Timestamp(d, tz="UTC") >= t0}


def goes_flares(day: str) -> dict:
    """NOAA SWPC event list for the day, if published (best effort; never blocks scoring)."""
    from src import goes

    try:
        f = goes.download_day(pd.Timestamp(day), prod_dir() / "goes_events", timeout=30)
    except Exception as e:  # network down, NOAA unavailable
        return {"status": f"not available: {type(e).__name__}", "flares": []}
    if f is None:
        return {"status": "no NOAA report for this day (yet)", "flares": []}
    ev = goes.parse_events_text(f.read_text(encoding="utf-8", errors="replace"), pd.Timestamp(day))
    keep = [
        {
            k: (None if v is None or (not isinstance(v, str) and pd.isna(v)) else str(v))
            for k, v in e.items()
            if k in ("begin", "peak", "end", "goes_class")
        }
        for e in ev
        if str(e.get("goes_class") or "")[:1] in "BCMX" and str(e.get("goes_class") or "")
    ]
    return {"status": "ok", "flares": keep}


def run_day(day: str, fetch_goes: bool = True) -> dict:
    """Validate -> features -> score -> store for one production day. Raises on a broken contract."""
    b = B.load(str(get_settings().bundle_dir))
    t = pd.Timestamp(day, tz="UTC")
    if t < start():
        raise PermissionError(f"{day} is before the production start {start():%Y-%m-%d} (evaluation/holdout data is locked)")
    counts = load_counts(day)
    S.validate(PV.counts_frame(counts), PV.RAW_COUNTS, f"raw counts {day}")
    feats = b.model_meta("now")["features"]
    X = sf.day_features(counts, t, None)[feats]
    S.validate(X, PV.features_schema(feats), f"features {day}")
    targets = base_targets(b)
    rows = []
    for target in targets:
        m = b.model_meta(target)
        p = np.clip(b.model(target).predict_proba(X[m["features"]])[:, 1].astype(float), 0, 1)
        thr = float(m["thresholds"]["A"])
        rows.append(
            pd.DataFrame(
                {
                    "time": X.index,
                    "target": target,
                    "model": m["registry_name"],
                    "model_version": m["version"],
                    "p_flare": p,
                    "threshold": thr,
                    "alert": p >= thr,
                }
            )
        )
    pred = S.validate(pd.concat(rows, ignore_index=True), S.PREDICTIONS, f"production predictions {day}")
    stored = replay.store(pred, get_settings().predictions_dir, tag="_production")
    X[["rate"]].rename(columns={"rate": "solexs_rate"}).to_parquet(prod_dir() / f"{day}_lightcurve.parquet")
    X.to_parquet(prod_dir() / f"{day}_features.parquet")  # for drift monitoring (check_drift)
    day_counts = counts[(counts.index > t) & (counts.index <= t + pd.Timedelta(days=1))]
    summary = {
        "day": day,
        "scored_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bundle_version": b.version,
        "rows": int(len(X)),
        "valid_fraction": round(len(day_counts) / 86400, 4),
        "first": str(X.index.min()),
        "last": str(X.index.max()),
        "targets": {
            tg: {
                "model": f"{g['model'].iloc[0]} v{g['model_version'].iloc[0]}",
                "threshold": float(g["threshold"].iloc[0]),
                "alerts": int(g["alert"].sum()),
                "alert_minutes": round(int(g["alert"].sum()) * 10 / 60, 1),
                "max_p": float(g["p_flare"].max()),
                "mean_p": float(g["p_flare"].mean()),
                "first_alert": str(g.loc[g["alert"], "time"].min()) if g["alert"].any() else None,
            }
            for tg, g in pred.groupby("target")
        },
        "not_scored": {
            t2: "needs long-context / spectral / GOES inputs not built by the production pipeline yet"
            for t2 in b.manifest["models"]
            if t2 not in targets
        },
        "goes": goes_flares(day) if fetch_goes else {"status": "skipped", "flares": []},
        "store": stored,
    }
    (prod_dir() / f"{day}.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8", newline="\n")
    return summary


def freshness() -> dict:
    avail = available_days()
    done = scored_days()
    last = done[-1] if done else None
    now = datetime.now(timezone.utc)
    age_h = None
    if last:
        js = json.loads((prod_dir() / f"{last}.json").read_text(encoding="utf-8"))
        age_h = round((now - datetime.fromisoformat(js["scored_at"])).total_seconds() / 3600, 1)
    return {
        "production_start": f"{start():%Y-%m-%d}",
        "latest_available_day": next(reversed(avail), None) if avail else None,
        "latest_scored_day": last,
        "pending_days": [d for d in avail if d not in set(done)],
        "scored_days": done,
        "hours_since_last_scoring": age_h,
        "checked_at": now.isoformat(timespec="seconds"),
    }


def recent_features(days: int = 30) -> pd.DataFrame | None:
    """Production feature rows of the last `days` scored days (None if there are none)."""
    done = scored_days()[-days:]
    parts = [
        pd.read_parquet(prod_dir() / f"{d}_features.parquet") for d in done if (prod_dir() / f"{d}_features.parquet").exists()
    ]
    return pd.concat(parts).sort_index() if parts else None
