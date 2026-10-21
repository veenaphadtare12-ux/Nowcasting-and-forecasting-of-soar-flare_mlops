# Lesson 09 — Data inventory: what data do we really have? Archives, listings, truncated zips, disk budgets

## What we built

A read-only script, `src/data_inventory.py`, that walks through every downloaded archive and writes one row per
archive to `reports/data_inventory.csv`:
- which instrument it holds and which dates it covers
- how big it is, compressed and uncompressed
- whether its files are already extracted

It found 77 HEL1OS observing sessions that had never been extracted, many overlapping our SoLEXS days. It also
showed that extracting them in full would fill the disk.

## Why it matters

Before cooking, you check the fridge. You might have ingredients you forgot about, and you check there's room on the
counter before unpacking the shopping. Skipping the inventory led us to a wrong belief: "HEL1OS and SoLEXS never
overlap". The data had been on disk all along, only not unpacked. In MLOps, **knowing exactly what data exists**
(and its versions, sizes and gaps) is the first step of data management. It's also what tools like DVC and data
catalogues formalise.

## Concepts

**Archive vs extracted data.** A `.zip` is a container: one file holding many compressed files. "Extracted" means
the files were copied out into normal folders that our code can read.

**Zip listing (central directory).** At the end of every zip is a table of contents: names, sizes and where each
file starts. Python's `zipfile` reads it, so we learn the uncompressed size *without extracting anything*.

**Local file headers.** Each file inside a zip also starts with a small header (`PK\x03\x04`, then the file name).
If a download was cut short, the table of contents at the end is missing ("truncated zip"), but the headers are
still there. Scanning for them lists what is inside, and decompressing each stream tells us whether that file is
complete.

**Bundle.** Our downloads were zips of zips: one big `solexs_*.zip` holding many day-zips, which hold the FITS files.

**Duplicates and versions.** The same day can exist twice: in `mlops_cp` and in `inner_solexs_zips`, or as two
processing versions (V211 and V311). The inventory records each copy. Extraction never overwrites, and the
pipeline's "newest version" rule picks which one to use.

**Read-only first.** Look before you touch: an inventory that changes nothing can be run as often as you like.

**Disk budget.** Uncompressed data can be much bigger than the zip: 4.2 GB of HEL1OS zips unpack to 28.6 GB. You
must compare the *uncompressed* total with free space and keep a safety margin (our rule: never below 15 GB free).

**Data you don't need.** Most of HEL1OS's size is photon event lists (19 GB) and spectra (5.7 GB). Our pipeline only
reads the light curves (3.6 GB) and auxiliary files (0.25 GB). Knowing which files your code actually uses is the
key to fitting data onto a disk.

## Tools used

| Tool | What it is | What it did here | Most useful commands |
|---|---|---|---|
| **zipfile** (Python) | Read and write zip archives | Listed 1,054 archives without extracting | `zipfile.ZipFile(p).infolist()`, `info.file_size`, `info.compress_size`, `z.open(info)` |
| **zlib** | Raw deflate (de)compression | Checked whether entries in truncated zips are complete | `zlib.decompressobj(-15)`, `.eof`, `.unused_data` |
| **struct** | Read binary records | Parsed zip local headers | `struct.unpack("<IHHHHHIIIHH", data[pos:pos+30])` |
| **find / du / df** | Shell tools | Searched D:, measured folders, checked free space | `find /d -iname '*AL1_SLX*'`, `du -sh <dir>`, `df -h /d` |

## Code walkthrough

### `src/data_inventory.py`

```python
DAY_RE = re.compile(r"AL1_SLX_L1_(\d{8})_v(\d+(?:\.\d+)*)")
SES_RE = re.compile(r"HLS_(\d{8})_(\d{6})_(\d+)sec_lev1_V(\d+)")
```
These read the date and version from file names. The first version of `DAY_RE` used `[\d.]+` and grabbed
`1.0.` (including the dot before `zip`); a unit test caught it.

```python
def listing(path):
    try:
        with zipfile.ZipFile(path) as z:
            return z.infolist(), "ok"
    except zipfile.BadZipFile:
        return None, "truncated"
```
A normal zip gives its table of contents. A zip without one is reported as truncated instead of crashing.

```python
        pos = data.find(b"PK\x03\x04", pos)                      # next local header
        _, _, flag, method, _, _, _, csize, usize, nlen, elen = struct.unpack("<IHHHHHIIIHH", data[pos:pos + 30])
        name = data[pos + 30: pos + 30 + nlen].decode("utf-8", "replace")
            d = zlib.decompressobj(-15)                            # raw deflate stream
            d.decompress(data[start:])
            complete = d.eof                                       # did the stream end properly?
```
In `scan_local_headers`, we find each header, read the file name, and decompress until the deflate stream says it
has ended. If the data runs out first, the entry is incomplete.

```python
    present = sum(1 for i in files if (root / i.filename).is_file() and (root / i.filename).stat().st_size == i.file_size)
    state = "yes" if present == len(files) else ("partial" if present else "no")
```
In `extracted_state`, an archive counts as extracted only if *every* file exists on disk with exactly the size the
listing promises.

```python
                with z.open(i) as src, open(target, "xb") as dst:  # "x": fail rather than overwrite
```
In `extract_missing` (not run yet), mode `"x"` refuses to open a file that already exists, so existing data can
never be overwritten, even by mistake.

## Hands-on

Activate the venv and work from the project folder.

**1. Run the inventory yourself.**
```
python -m src.data_inventory inventory
```
*Expected:* a summary ending with `session HEL1OS ok no 77` and `yes 54`, and `day SoLEXS ok yes 913`.
It changes no data; run it as often as you like.

**2. Explore the CSV.**
```
python -c "import pandas as pd; d=pd.read_csv('reports/data_inventory.csv'); print(d.groupby(['instrument','kind','extracted']).agg(n=('archive','size'), gb=('uncompressed_mb', lambda x: round(x.sum()/1e3,1))))"
```
*Expected:* the HEL1OS sessions with `extracted = no` total about 28.6 GB uncompressed. Duplicates are counted
twice in this table, so think about why the "yes" rows look bigger than the 6.4 GB on disk.

**3. Look inside a zip without extracting it.**
```
python -c "import zipfile; z=zipfile.ZipFile(r'D:\MLOPS_CP\Data\original_zips\downloads_bundles\inner_hel1os_zips\HLS_20250410_000008_43184sec_lev1_V112.zip'); [print(i.file_size, i.filename) for i in z.infolist()]"
```
*Expected:* 22 entries. Find `events/evt.fits`: it's the largest file by far. Which files does our pipeline actually read?

**4. Read a truncated zip.**
```
python -c "from pathlib import Path; from src import data_inventory as i; e=i.scan_local_headers(Path(r'D:\MLOPS_CP\Data\original_zips\downloads_bundles\solexs_2026Sep15T045132804.zip')); print(len(e), sum(x['complete'] for x in e), e[-1])"
```
*Expected:* `20 19` and a last entry with `'complete': False`. That's the file that was being downloaded when the
transfer stopped.

**5. Do the disk arithmetic.** Run `df -h /d` (Git Bash) or check D: in Explorer. With 27 GB free and 28.6 GB to
unpack, what's left? What if you only extract light curves and aux files (3.85 GB)?

## Break it on purpose

Make the version parser sloppy again and let the test catch it.

1. In `src/data_inventory.py`, change `DAY_RE` back to `r"AL1_SLX_L1_(\d{8})_v([\d.]+)"`.
2. Run `pytest tests/test_inventory.py -q`.
3. *Expected:* `test_classify_archive_names` fails, showing `'1.0.'` where `'1.0'` was expected.
4. Undo: `git checkout -- src/data_inventory.py`, then rerun. Expected: 2 passed.

## Check yourself

1. How can we know an archive's uncompressed size without extracting it?
2. Why can Python's `zipfile` not open the two truncated bundles, and how do we still list their contents?
3. What does "extracted = yes" require in our script?
4. Why does extraction open files with mode `"x"`?
5. HEL1OS needs 28.6 GB but our pipeline only reads about 3.9 GB of it. Name two ways to fit the useful data on the disk.

## Questions to discuss with my tutor

1. Should a data inventory like this become a DVC stage, or be replaced by `dvc add` on the archives? What are the
   trade-offs with 30+ GB of raw data?
2. Extracting only the files the code needs saves 25 GB, but it breaks the "same structure as the original"
   expectation. Is a partial extract acceptable for raw data, and how would you document it?
3. My earlier mistake (deleting folders I *assumed* were empty) went unnoticed for a month. What process or tool
   would have caught it sooner?

## Key numbers

**Archives:**
- **Total:** 1,054 archives, all in `D:\MLOPS_CP\Data\original_zips`.
- **SoLEXS:** 913 day zips (with duplicates) and 5 bundles, 2 of them truncated. **No new SoLEXS days.**

**HEL1OS:**
- **Sessions:** 131 zips (104 unique), of which **77 are not extracted**. That's 4.2 GB compressed and 28.6 GB
  uncompressed (events 19.0, spectra 5.7, light curves 3.6, aux 0.25 GB).
- **New sessions overlapping usable SoLEXS days:** 22 in tune (11 days), 13 in val (6 days), 17 in test (9 days;
  counted only).

**Disk:** D: has 27 GB free, so full extraction is impossible without freeing space.

---

<details>
<summary><b>Answers (spoiler — try first!)</b></summary>

1. From the zip's table of contents (central directory). `zipfile.ZipFile(p).infolist()` gives each entry's
   `file_size` without extracting.
2. The table of contents sits at the end of the zip, and the download was cut before it was written. Each file still
   starts with a local header, so we scan for those, read the names, and decompress each stream to see whether it's
   complete.
3. Every non-folder entry in the archive exists at the expected path, with exactly the size from the listing.
4. `"x"` (exclusive create) fails if the file already exists, so extraction can never overwrite existing raw data.
5. Extract only light curves and aux files (about 3.9 GB). Or free space elsewhere, for example by moving the
   unrelated 23 GB `tusimple.zip` or the duplicate archive copies to another drive. That's the user's decision.

</details>
