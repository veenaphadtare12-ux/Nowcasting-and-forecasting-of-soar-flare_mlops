"""Inventory (read-only) and safe extraction of the Aditya-L1 archives.

    python -m src.data_inventory inventory   # list every archive, dates, sizes, extracted?  -> reports/data_inventory.csv
    python -m src.data_inventory extract     # extract only what is missing (never overwrites), verify, re-inventory

Archive kinds under `paths.archive_root`:
* SoLEXS day zip   AL1_SLX_L1_<YYYYMMDD>_v<ver>.zip -> entries AL1_SLX_L1_<date>_v<ver>/SDD{1,2}/...  (into data_root_solexs)
* HEL1OS session   HLS_<YYYYMMDD>_<HHMMSS>_<dur>sec_lev1_V<ver>.zip -> entries YYYY/MM/DD/HLS_.../...  (into data_root_hel1os)
* bundle           solexs_*.zip / hel1os_*.zip: a zip of day/session zips (as downloaded)
Two solexs bundles are truncated downloads (no central directory); their entries are listed by scanning local
file headers, and an entry counts as recoverable only if its compressed stream decompresses completely.
Raw data is never modified or deleted: extraction only creates files that do not exist yet.
"""
from __future__ import annotations

import re
import struct
import sys
import zipfile
import zlib
from pathlib import Path

import pandas as pd

from src import config

DAY_RE = re.compile(r"AL1_SLX_L1_(\d{8})_v(\d+(?:\.\d+)*)")
SES_RE = re.compile(r"HLS_(\d{8})_(\d{6})_(\d+)sec_lev1_V(\d+)")
REPORT = config.PROJECT_ROOT / "reports" / "data_inventory.csv"


def archive_root() -> Path:
    return config.path("archive_root")


# ---------------------------------------------------------------- reading archives
def scan_local_headers(path: Path) -> list[dict]:
    """List entries of a (possibly truncated) zip by walking its local file headers.

    Works for streamed entries (sizes in a trailing data descriptor): the deflate stream is decompressed to find
    where it ends. An entry is `complete` only if its whole stream is present.
    """
    data = path.read_bytes()
    out, pos = [], 0
    while True:
        pos = data.find(b"PK\x03\x04", pos)
        if pos < 0 or pos + 30 > len(data):
            break
        _, _, flag, method, _, _, _, csize, usize, nlen, elen = struct.unpack("<IHHHHHIIIHH", data[pos:pos + 30])
        name = data[pos + 30: pos + 30 + nlen].decode("utf-8", "replace")
        start = pos + 30 + nlen + elen
        complete, end = False, start
        if method == 8:
            d = zlib.decompressobj(-15)
            try:
                d.decompress(data[start:])
                complete = d.eof
                end = len(data) - len(d.unused_data) if d.eof else len(data)
            except zlib.error:
                complete = False
        elif method == 0 and csize:
            complete = start + csize <= len(data)
            end = start + csize
        out.append({"name": name, "complete": bool(complete), "offset": pos})
        pos = max(end, pos + 4)
    return out


def listing(path: Path) -> tuple[list[zipfile.ZipInfo] | None, str]:
    try:
        with zipfile.ZipFile(path) as z:
            return z.infolist(), "ok"
    except zipfile.BadZipFile:
        return None, "truncated"


def _date(s: str) -> pd.Timestamp:
    return pd.Timestamp(s)


def classify(name: str) -> tuple[str, str, str | None, str | None]:
    """(kind, instrument, date, version) from an archive file name."""
    if m := DAY_RE.search(name):
        return "day", "SoLEXS", m.group(1), m.group(2)
    if m := SES_RE.search(name):
        return "session", "HEL1OS", m.group(1), m.group(4)
    if name.lower().startswith("solexs_"):
        return "bundle", "SoLEXS", None, None
    if name.lower().startswith("hel1os_"):
        return "bundle", "HEL1OS", None, None
    return "other", "?", None, None


def _dest_root(instrument: str) -> Path:
    return config.solexs_root() if instrument == "SoLEXS" else config.hel1os_root()


def extracted_state(infos: list[zipfile.ZipInfo], instrument: str) -> tuple[str, int, int]:
    """('yes' | 'partial' | 'no', files present with matching size, files in archive)."""
    root = _dest_root(instrument)
    files = [i for i in infos if not i.is_dir()]
    present = sum(1 for i in files if (root / i.filename).is_file() and (root / i.filename).stat().st_size == i.file_size)
    state = "yes" if present == len(files) else ("partial" if present else "no")
    return state, present, len(files)


def inventory() -> pd.DataFrame:
    rows = []
    for f in sorted(archive_root().rglob("*.zip")):
        kind, inst, date, ver = classify(f.name)
        infos, status = listing(f)
        row = {"archive": str(f), "kind": kind, "instrument": inst, "version": ver, "status": status,
               "compressed_mb": round(f.stat().st_size / 1e6, 2)}
        if kind in ("day", "session") and infos is not None:
            files = [i for i in infos if not i.is_dir()]
            st, present, n = extracted_state(infos, inst)
            row |= {"date_start": date, "date_end": date, "n_files": n, "uncompressed_mb": round(sum(i.file_size for i in files) / 1e6, 2),
                    "extracted": st, "files_present": present}
        elif kind == "bundle":
            if infos is not None:
                inner = [i.filename for i in infos if not i.is_dir()]
                unc = sum(i.file_size for i in infos)
                complete = len(inner)
            else:
                ents = [e for e in scan_local_headers(f) if not e["name"].endswith("/")]
                inner = [e["name"] for e in ents if e["complete"]]
                unc, complete = None, len(inner)
                row["note"] = f"{len(ents)} entries found, {complete} complete"
            dates = sorted(classify(n)[2] for n in inner if classify(n)[2])
            have = {p.name for p in (f.parent / f"inner_{inst.lower() if inst == 'SoLEXS' else 'hel1os'}_zips").glob("*.zip")} \
                if inst == "SoLEXS" else {p.name for p in (f.parent / "inner_hel1os_zips").glob("*.zip")}
            missing = [Path(n).name for n in inner if Path(n).name not in have]
            row |= {"date_start": dates[0] if dates else None, "date_end": dates[-1] if dates else None, "n_files": complete,
                    "uncompressed_mb": round(unc / 1e6, 2) if unc else None,
                    "extracted": "yes" if not missing else ("partial" if len(missing) < len(inner) else "no"),
                    "files_present": complete - len(missing), "missing_inner": ";".join(missing[:50])}
        rows.append(row)
    df = pd.DataFrame(rows)
    REPORT.parent.mkdir(exist_ok=True)
    df.to_csv(REPORT, index=False, lineterminator="\n")
    return df


# ---------------------------------------------------------------- extraction (only missing files, never overwrite)
def verify_fits(paths: list[Path]) -> tuple[int, list[str]]:
    from astropy.io import fits

    bad = []
    for p in paths:
        if p.suffix in (".fits",) or p.name.endswith((".lc.gz", ".gti.gz", ".pi.gz", ".hk.gz")):
            try:
                with fits.open(p) as h:
                    _ = [x.header for x in h]
            except Exception as e:  # noqa: BLE001
                bad.append(f"{p.name}: {e}")
    return len(paths), bad


def extract_missing(df: pd.DataFrame) -> pd.DataFrame:
    """Extract day/session zips whose files are not (all) on disk. Existing files are never overwritten.
    Returns one row per extracted archive with verification results."""
    log = []
    todo = df[df["kind"].isin(["day", "session"]) & (df["status"] == "ok") & (df["extracted"] != "yes")]
    for _, r in todo.iterrows():
        root = _dest_root(r["instrument"])
        written, skipped, mismatch = [], 0, []
        with zipfile.ZipFile(r["archive"]) as z:
            for i in z.infolist():
                target = root / i.filename
                if i.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if target.exists():
                    skipped += 1
                    if target.stat().st_size != i.file_size:
                        mismatch.append(i.filename)  # keep the existing file; report it
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(i) as src, open(target, "xb") as dst:  # "x": fail rather than overwrite
                    while chunk := src.read(1 << 20):
                        dst.write(chunk)
                if target.stat().st_size != i.file_size:
                    mismatch.append(i.filename)
                written.append(target)
        n, bad = verify_fits(written)
        log.append({"archive": r["archive"], "files_written": len(written), "files_skipped_existing": skipped,
                    "size_mismatch": len(mismatch), "fits_checked": n, "fits_failed": len(bad), "fits_errors": "; ".join(bad[:5])})
        print(f"{Path(r['archive']).name}: wrote {len(written)}, kept {skipped} existing, fits bad {len(bad)}", flush=True)
    return pd.DataFrame(log)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "inventory"
    inv = inventory()
    if cmd == "extract":
        res = extract_missing(inv)
        inv = inventory()  # re-inventory after extraction
        if len(res):
            inv = inv.merge(res, on="archive", how="left")
            inv.to_csv(REPORT, index=False, lineterminator="\n")
    print(inv.groupby(["kind", "instrument", "status", "extracted"]).size())
