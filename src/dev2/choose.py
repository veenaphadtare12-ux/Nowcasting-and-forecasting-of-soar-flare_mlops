"""FINAL_CHOICE_2: mechanical choice from the development results (written before any dev2 result was read).

    python -m src.dev2.choose choose   # reports/dev2/choice.json + params.yaml dev2.final.targets (choice only)
    python -m src.dev2.choose doc      # docs/FINAL_CHOICE_2.md (after src.dev2.final froze the models)

Rule, per target (acceptance rule = docs/IMPROVEMENTS.md, unchanged; 14 months, >= 9 better):
1. Learner = the reference learner (LogReg / XGBoost) with the higher mean monthly TSS.
2. Aditya-only candidates, each compared with the reference using the same learner: R2 primary (r2a; R2 targets),
   R3 stacked pretrained score (R2 targets), and the FINAL_CHOICE.md feature sets (c_30m: E2+E3+E5 ensemble;
   m_30m: E5). Among the KEPT ones the highest mean monthly TSS wins; none kept -> base 44 features.
3. GOES-derived inputs are adopted only if they pass the rule ON THEIR OWN: E6 vs reference, R2 secondary vs R2
   primary, m_30m E5+E6 vs E5. If one passes, the champion is the `with_goes` variant (chosen Aditya blocks + the
   passing GOES blocks); otherwise the champion is `aditya`. A `with_goes` variant is frozen either way (chosen
   blocks + E6, and + GOES counts + SRS for the R2 targets) so every holdout2 result is shown with and without GOES.
Simpler wins ties. R1: per input variant the learner with the higher pooled per-trigger TSS for >= M, over all k.
"""
from __future__ import annotations

import hashlib
import json
import sys

import numpy as np
import yaml

from src import config
from src.dev2 import protocol as pr
from src.dev2 import run as rn

OUT = config.PROJECT_ROOT / "reports" / "dev2"


def _maybe(name: str) -> dict | None:
    p = OUT / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def choose() -> dict:
    ref = rn.read("ref")
    e6, r2a, r2b, champ, r3, r1 = (_maybe(n) for n in ("e6", "r2a", "r2b", "champ", "r3", "r1"))
    p = pr.P()
    out = {"targets": {}, "r1": {}}
    for t in p["targets"]:
        L = rn.best_learner(ref, t)
        cands = []           # (name, blocks, learner, comparison)
        if r2a and t in r2a["comparison_vs_ref"]:
            cands.append(("r2a", ["ax"], L, r2a["comparison_vs_ref"][t]))
        if r3 and t in r3["targets"]:
            cands.append(("r3_stack", ["r3"], L, r3["targets"][t]["comparison_vs_ref"]["stack"]))
        if champ:
            if t == "c_30m":
                cands.append(("champ_c30", ["long", "drift", "spectral"], "ensemble", champ["comparison_vs_ref"]["c_30m"]))
            if t == "m_30m":
                cands.append(("champ_m30_E5", ["spectral"], "logreg", champ["comparison_vs_ref"]["m_30m_aditya"]))
        kept = [c for c in cands if c[3]["decision"] == "KEPT"]
        best = max(kept, key=lambda c: c[3]["exp_mean"]) if kept else ("base", [], L, None)
        goes_tests = []
        if e6 and t in e6["comparison_vs_ref"]:
            goes_tests.append(("e6", ["goes"], e6["comparison_vs_ref"][t]))
        if r2b and t in (r2b.get("comparison_vs_r2a") or {}):
            goes_tests.append(("r2b_vs_r2a", ["gc", "srs"], r2b["comparison_vs_r2a"][t]))
        if champ and t == "m_30m":
            goes_tests.append(("m30_E6_vs_E5", ["goes"], pr.compare(champ["months"]["m_30m_aditya"], "logreg",
                                                                    champ["months"]["m_30m"], "logreg")))
        passed = [g for g in goes_tests if g[2]["decision"] == "KEPT"]
        if passed:
            gblocks = sorted({b for g in passed for b in g[1]})
        else:
            gblocks = ["goes"] + (["gc", "srs"] if t in p["r2_targets"] else [])
        out["targets"][t] = {
            "learner": best[2], "blocks": best[1], "idea": best[0], "goes_blocks": gblocks,
            "choice": "with_goes" if passed else "aditya",
            "candidates": {c[0]: {k: c[3][k] for k in ("ref_mean", "exp_mean", "months_better", "need", "decision")} for c in cands},
            "goes_tests": {g[0]: {k: g[2][k] for k in ("ref_mean", "exp_mean", "months_better", "need", "decision")} for g in goes_tests},
            "reference": ref["summary"][t][L]}
    if r1:
        for var in ("aditya", "with_goes"):
            score = {k: np.mean([r1["variants"][f"k{kk}_{var}"]["summary"][k]["m_pooled"]["tss"] for kk in (0, 1, 2, 3, 5)])
                     for k in ("logreg", "xgb")}
            out["r1"][var] = "logreg" if score["logreg"] >= score["xgb"] else "xgb"
            out["r1"][f"{var}_mean_pooled_tss"] = score
    rn.write("choice", out)
    # copy the machine-readable choice into params.yaml (dev2.final.targets, dev2.final.r1)
    pf = config.PARAMS_FILE
    txt = pf.read_text(encoding="utf-8")
    P = yaml.safe_load(txt)
    fin = P["dev2"]["final"]
    fin["targets"] = {t: {k: v[k] for k in ("learner", "blocks", "goes_blocks", "choice", "idea")} for t, v in out["targets"].items()}
    fin["r1"] = {k: out["r1"][k] for k in ("aditya", "with_goes")} if out["r1"] else {}
    # dev2.final is the last block of params.yaml: keep its header and date lines, rewrite targets / r1 only
    lines = txt.split("\n")
    i = next(k for k, line in enumerate(lines) if line.startswith("  final:"))
    keep = [line for line in lines[i + 1:] if line.startswith("    ") and not line.startswith("     ")
            and line.split(":")[0].strip() in ("calibration_start", "threshold_start", "bootstrap")]
    block = yaml.safe_dump({k: fin[k] for k in ("targets", "r1")}, sort_keys=False, default_flow_style=None, width=110)
    body = ["    " + line for line in block.rstrip().split("\n")]
    pf.write_text("\n".join(lines[: i + 1] + keep + body) + "\n", encoding="utf-8", newline="\n")
    config.load_params.cache_clear()
    for t, v in out["targets"].items():
        print(f"  {t:7s} {v['learner']:8s} idea={v['idea']:12s} blocks={v['blocks']} champion={v['choice']} goes_blocks={v['goes_blocks']}")
    print("  R1:", out["r1"])
    return out


def sha(p) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


if __name__ == "__main__":
    {"choose": choose}[sys.argv[1]]()
