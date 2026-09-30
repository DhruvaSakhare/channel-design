#!/usr/bin/env python3
"""
Stage 4 — collect best designs.

Copies the best RF3 model CIF for each passing design to best_designs/
and writes a ranked metrics CSV.

Run after 05_rf3_score.py:
  python scripts/06_collect_best.py

Output:
  work/<experiment>/best_designs/   — decompressed CIFs + best_designs.csv
"""
import sys
import gzip
import os
import importlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
C = importlib.import_module(importlib.import_module("partial_diffusion").default_config())

try:
    import pandas as pd
except ImportError:
    sys.exit("pandas is required: pip install pandas")

C.make_workdirs()

metrics_csv = C.SCORES_DIR / "rf3_metrics.csv"
if not metrics_csv.exists():
    sys.exit(f"Metrics CSV not found: {metrics_csv}\nRun 05_rf3_score.py first.")

df = pd.read_csv(metrics_csv).rename(columns={
    "best_binder_plddt": "enzyme_plddt",
    "AF_best_min_pae":   "substrate_min_pae",
    "AF_ipsae_at_best":  "substrate_ipsae",
    "AG_best_min_pae":   "heme_min_pae",
    "AG_ipsae_at_best":  "heme_ipsae",
})

pass_mask = (
    (df["enzyme_plddt"]      > C.PLDDT_CUT) &
    (df["substrate_min_pae"] < C.PAE_CUT) &
    (df["substrate_ipsae"]   > C.IPSAE_CUT)
)
df_best = df[pass_mask].copy().sort_values("enzyme_plddt", ascending=False)
print(f"{len(df_best)} / {len(df)} designs pass thresholds "
      f"(pLDDT>{C.PLDDT_CUT}, PAE<{C.PAE_CUT}, ipSAE>{C.IPSAE_CUT})")

if df_best.empty:
    print("No designs passed — consider relaxing thresholds in config.py.")
    sys.exit(0)

copied, missing = 0, []
for _, row in df_best.iterrows():
    did  = row["design_id"]
    bidx = int(row.get("best_batch_idx", 0)) if pd.notna(row.get("best_batch_idx")) else 0
    sf   = Path(row["score_file"])
    src  = sf.parent / f"{did}_model_{bidx}.cif.gz"
    dst  = C.BEST_DIR / f"{did}_model_{bidx}.cif"
    if src.exists():
        with gzip.open(src, "rb") as gz_in, open(dst, "wb") as out:
            out.write(gz_in.read())
        copied += 1
    else:
        missing.append(str(src))

best_csv = C.BEST_DIR / "best_designs.csv"
df_best[["design_id", "enzyme_plddt",
         "substrate_min_pae", "substrate_ipsae",
         "heme_min_pae", "heme_ipsae",
         "score_file"]].to_csv(best_csv, index=False)

print(f"\n--- SUMMARY ---")
print(f"  Passing designs : {len(df_best)} / {len(df)}")
print(f"  CIFs copied to  : {C.BEST_DIR}/")
print(f"  Rankings CSV    : {best_csv}")
if missing:
    print(f"\n  WARNING: {len(missing)} source CIF(s) not found — RF3 may not have finished for those designs")
if copied > 0:
    print(f"\n  Transfer best designs to your laptop:")
    print(f"    scp -r {C.BEST_DIR} your_laptop:/path/to/destination/")
    print(f"  Then open the .cif files in PyMOL or ChimeraX.")
print(f"\nDone!")
