"""Build notebooks/01_eda.ipynb from cells (takeaways come from notebooks/eda_takeaways.json), then execute it.

    python notebooks/build_eda_notebook.py

The notebook uses the tune and validation periods only (asserted in its first cell).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import nbformat as nbf

ROOT = Path(__file__).resolve().parents[1]
NB = ROOT / "notebooks" / "01_eda.ipynb"
TAKE = json.loads((ROOT / "notebooks" / "eda_takeaways.json").read_text(encoding="utf-8"))

cells = [
    ("md", "# Exploratory data analysis: SoLEXS + HEL1OS + GOES\n\nTune (2025-04-09 … 2026-01-31) and validation "
           "(2026-02-01 … 2026-05-31) periods only. The test period is never loaded; the first cell asserts it. "
           "Figures are also saved to `docs/figures/eda/`. Findings are summarised in `docs/EDA_SUMMARY.md`."),
    ("code", "import os, sys, json\n"
             "ROOT = os.path.abspath('..') if os.path.basename(os.getcwd()) == 'notebooks' else os.getcwd()\n"
             "os.chdir(ROOT); sys.path.insert(0, ROOT)\n"
             "import pandas as pd, numpy as np\n"
             "from IPython.display import Image, display\n"
             "from src import config, eda\n"
             "# --- guard: only tune + validation may be used ------------------------------------------------\n"
             "assert eda.HI == config.period_bounds('val')[1], 'EDA must stop at the end of validation'\n"
             "assert eda.HI <= config.period_bounds('test')[0], 'EDA window reaches the test period'\n"
             "qc, m, ev, g, pairs = eda.load_qc(), eda.load_minutes(), eda.load_events(), eda.load_goes(), eda.load_pairs()\n"
             "eda.check_no_test(qc, m, ev, g)\n"
             "print('window:', eda.LO, '->', eda.HI, '| days', len(qc), '| minutes', len(m), '| events', len(ev), '| GOES flares', len(g))"),
    ("md", "## 1. Data coverage"),
    ("code", "cov = eda.coverage(qc, m); display(Image(cov['fig_calendar'])); display(Image(cov['fig_gaps']))\n"
             "{k: v for k, v in cov.items() if not k.startswith('fig')}"),
    ("md", TAKE["coverage"]),
    ("md", "## 2. Long-term light curve"),
    ("code", "lt = eda.long_term(m, g); display(Image(lt['fig'])); {k: v for k, v in lt.items() if k != 'fig'}"),
    ("md", TAKE["long_term"]),
    ("md", "## 3. Solar activity trend"),
    ("code", "at = eda.activity_trend(m, g); display(Image(at['fig']))\n"
             "{k: v for k, v in at.items() if k not in ('fig', 'monthly_counts')}"),
    ("md", TAKE["activity"]),
    ("md", "## 4. Flare profiles (superposed epoch, aligned on SoLEXS onset)"),
    ("code", "se = eda.superposed_epoch(m, ev); display(Image(se['fig'])); {k: v for k, v in se.items() if k != 'fig'}"),
    ("md", TAKE["profiles"]),
    ("md", "## 5. Flare statistics"),
    ("code", "fs = eda.flare_stats(ev); display(Image(fs['fig_dist'])); display(Image(fs['fig_scatter']))\n"
             "{k: v for k, v in fs.items() if not k.startswith('fig')}"),
    ("md", TAKE["stats"]),
    ("md", "## 6. Detector vs GOES"),
    ("code", "dg = eda.detector_vs_goes(m, ev, g, pairs); display(Image(dg['fig'])); display(Image(dg['fig_missed']))\n"
             "{k: v for k, v in dg.items() if not k.startswith('fig')}"),
    ("md", TAKE["detector"]),
    ("md", "## 7. Features (quiet-start rows, target: ≥C flare within 60 min)"),
    ("code", "cols = None  # all columns\n"
             "d = eda.load_dataset(); eda.check_no_test(d)\n"
             "from src import dataset\n"
             "soft = [c for c in dataset.feature_columns(d) if not c.startswith('hx_') and c != 'hel1os_available']\n"
             "fe = eda.feature_eda(d, soft); display(Image(fe['fig_dist'])); display(Image(fe['fig_corr']))\n"
             "print(len(soft), 'SoLEXS features'); {k: v for k, v in fe.items() if not k.startswith('fig')}"),
    ("md", TAKE["features"]),
    ("md", "## 8. Label base rates"),
    ("code", "br = eda.base_rates(d); display(Image(br['fig'])); {k: v for k, v in br.items() if k != 'fig'}"),
    ("md", TAKE["base_rates"]),
    ("md", "## 9. HEL1OS (hard X-rays), overlapping data only"),
    ("code", "chan = eda.load_hel1os_channels()\n"
             "if chan is not None: eda.check_no_test(chan)\n"
             "hx = eda.hel1os_eda(chan, m, ev, g, d)\n"
             "for k in ('fig_neupert', 'fig_hardness', 'fig_example'):\n"
             "    if k in hx: display(Image(hx[k]))\n"
             "{k: v for k, v in hx.items() if not k.startswith('fig')}"),
    ("md", TAKE["hel1os"]),
    ("code", "summary = dict(coverage=cov, long_term=lt, activity=at, profiles=se, stats=fs, detector=dg, features=fe,\n"
             "               base_rates=br, hel1os=hx)\n"
             "json.dump(summary, open('reports/eda_numbers.json', 'w', newline='\\n'), indent=2, default=str); print('saved reports/eda_numbers.json')"),
]

nb = nbf.v4.new_notebook()
nb["metadata"]["kernelspec"] = {"name": "solar-flare", "display_name": "solar-flare (py3.12)", "language": "python"}
nb["cells"] = [nbf.v4.new_markdown_cell(s) if k == "md" else nbf.v4.new_code_cell(s) for k, s in cells]
NB.write_text(nbf.writes(nb), encoding="utf-8", newline="\n")
subprocess.run([sys.executable, "-m", "jupyter", "nbconvert", "--to", "notebook", "--execute", "--inplace",
                "--ExecutePreprocessor.timeout=1800", "--ExecutePreprocessor.kernel_name=solar-flare", str(NB)],
               check=True, cwd=ROOT)
print("executed", NB)
