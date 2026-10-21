"""Archive inventory: name parsing and reading truncated zips (read-only helpers)."""
import io
import zipfile

from src import data_inventory as inv


def test_classify_archive_names():
    assert inv.classify("AL1_SLX_L1_20250410_v1.0.zip") == ("day", "SoLEXS", "20250410", "1.0")
    assert inv.classify("HLS_20250410_000008_43184sec_lev1_V112.zip") == ("session", "HEL1OS", "20250410", "112")
    assert inv.classify("solexs_2026Sep15T045132804.zip")[0:2] == ("bundle", "SoLEXS")
    assert inv.classify("hel1os_2026Sep16T040345431.zip")[0:2] == ("bundle", "HEL1OS")
    assert inv.classify("tusimple.zip")[0] == "other"


def test_truncated_zip_entries_are_listed_and_only_complete_ones_count(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("AL1_SLX_L1_20250101_v1.0.zip", b"a" * 5000 + bytes(range(256)) * 50)
        z.writestr("AL1_SLX_L1_20250102_v1.0.zip", bytes(range(256)) * 400)
    data = buf.getvalue()
    cut = data.find(b"PK\x03\x04", 10) + 60  # keep the first entry whole, cut the second one short
    f = tmp_path / "solexs_truncated.zip"
    f.write_bytes(data[:cut])
    assert inv.listing(f) == (None, "truncated")
    entries = inv.scan_local_headers(f)
    assert [e["name"] for e in entries] == ["AL1_SLX_L1_20250101_v1.0.zip", "AL1_SLX_L1_20250102_v1.0.zip"]
    assert [e["complete"] for e in entries] == [True, False]


def test_extraction_writes_only_selected_files_and_never_overwrites(tmp_path, monkeypatch):
    import pandas as pd

    root = tmp_path / "HELIOS"
    monkeypatch.setattr(inv, "_dest_root", lambda instrument: root)
    sess = "2025/04/10/HLS_20250410_000008_43184sec_lev1_V112"
    zp = tmp_path / "HLS_20250410_000008_43184sec_lev1_V112.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr(f"{sess}/cdte/lightcurve_cdte1.txt", "new-lc")
        z.writestr(f"{sess}/aux/gticdte1.txt", "new-gti")
        z.writestr(f"{sess}/events/evt.fits", "big events")
    existing = root / sess / "aux" / "gticdte1.txt"
    existing.parent.mkdir(parents=True)
    existing.write_text("OLD")  # different size on purpose
    df = pd.DataFrame([{"archive": str(zp), "kind": "session", "instrument": "HEL1OS", "status": "ok", "extracted": "partial"}])
    log = inv.extract_missing(df)
    assert (root / sess / "cdte" / "lightcurve_cdte1.txt").read_text() == "new-lc"  # selected -> written
    assert not (root / sess / "events" / "evt.fits").exists()                        # not selected -> stays in zip
    assert existing.read_text() == "OLD"                                              # never overwritten
    r = log.iloc[0]
    assert r["files_expected"] == 2 and r["files_written"] == 1 and r["files_skipped_existing"] == 1
    assert r["size_mismatch"] == 1  # the clash is reported, not silently resolved
