#!/usr/bin/env python3
"""
Stage 1 (post) — parse RFD3 metrics and filter broken backbones.

Run after the RFD3 job finishes:
  python scripts/02_rfd3_process.py

Passing backbones (no chain breaks, no clashes) are copied to
  work/<experiment>/diffusion_out/passing/

Then run:  python scripts/03_mpnn_submit.py
"""
import sys
import csv
import glob
import json
import math
import shutil
import os
import importlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
C = importlib.import_module(importlib.import_module("partial_diffusion").default_config())

C.make_workdirs()

# --- Parse RFD3 JSON metrics ---
json_paths = sorted(glob.glob(str(C.DIFFUSION_DIR / "*.json")))
if not json_paths:
    sys.exit(f"No JSON files in {C.DIFFUSION_DIR} — run RFD3 first (01_rfd3_submit.py).")

rows = []
all_keys = {"json_path"}

for jp in json_paths:
    with open(jp) as f:
        data = json.load(f)
    metrics = data.get("metrics", {})
    row = {"json_path": os.path.abspath(jp)}
    for k, v in metrics.items():
        if k in ("diffused_com", "fixed_com") and isinstance(v, (list, tuple)) and len(v) == 3:
            row[f"{k}_x"], row[f"{k}_y"], row[f"{k}_z"] = v
            all_keys.update({f"{k}_x", f"{k}_y", f"{k}_z"})
        else:
            row[k] = v
            all_keys.add(k)
    rows.append(row)

metrics_csv = C.SCORES_DIR / "rfd3_metrics.csv"
fieldnames = ["json_path"] + sorted(k for k in all_keys if k != "json_path")
with open(metrics_csv, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

print(f"RFD3 metrics ({len(rows)} designs) -> {metrics_csv}")

# --- Filter: drop chain breaks and clashes ---
# Partial diffusion tolerates a few chain breaks in remodelled loops (≤3 ok).
# Backbone clashes are hard failures; sidechain clashes are tolerated.
MAX_CHAINBREAKS = 3
bb_clash = "n_clashing.interresidue_clashes_w_backbone"
# sc_clash = "n_clashing.interresidue_clashes_w_sidechain" # to strict

passing = []
for row in rows:
    if row.get("n_chainbreaks", MAX_CHAINBREAKS + 1) > MAX_CHAINBREAKS:
        continue
    if bb_clash in row and row[bb_clash] != 0:
        continue
    # if sc_clash in row and row[sc_clash] != 0: # to strict
    #     continue
    passing.append(row)

print(f"Passing backbones: {len(passing)} / {len(rows)}")

if not passing:
    print("WARNING: no backbones passed filters — check RFD3 output quality.")
    sys.exit(0)

# --- Copy passing designs ---
filtered_dir = C.DIFFUSION_DIR / "passing"
filtered_dir.mkdir(exist_ok=True)

copied = 0
for row in passing:
    jp = Path(row["json_path"])
    if not jp.exists():
        print(f"  [missing] {jp}")
        continue
    for src in [jp, jp.with_suffix(".cif"), jp.with_suffix(".cif.gz")]:
        # handle double suffix .cif.gz
        if src == jp:
            dst = filtered_dir / jp.name
            if not dst.exists():
                shutil.copy2(jp, dst)
                copied += 1
        elif src.exists():
            dst = filtered_dir / src.name
            if not dst.exists():
                shutil.copy2(src, dst)
                copied += 1
    # also handle stem.cif and stem.cif.gz explicitly
    stem = jp.stem  # e.g. "rfd3_run_0"
    for ext in (".cif", ".cif.gz"):
        src = jp.parent / (stem + ext)
        if src.exists():
            dst = filtered_dir / src.name
            if not dst.exists():
                shutil.copy2(src, dst)
                copied += 1

print(f"Copied {copied} file(s) to {filtered_dir}")

print(f"\n--- SUMMARY ---")
print(f"  Backbones generated : {len(rows)}")
print(f"  Backbones passing   : {len(passing)}  (in diffusion_out/passing/)")
print(f"  Quality metrics     : {metrics_csv}")
print(f"\n  To inspect a backbone in PyMOL, unzip it first:")
print(f"    gunzip -k {C.DIFFUSION_DIR}/passing/*.cif.gz")
if not passing:
    print(f"\n  WARNING: 0 backbones passed — check rfd3_metrics.csv for n_chainbreaks / clashes.")
    print(f"  You may need to re-run RFD3 with a different PARTIAL_T or check the input PDB.")
else:
    print(f"\nNext:  python partial_diffusion/scripts/03_mpnn_submit.py")
