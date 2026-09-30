#!/usr/bin/env python3
"""
Stage 3 (post) — score RF3 outputs and save metrics CSV.

Run after RF3 jobs finish:
  python scripts/05_rf3_score.py

Writes:
  work/<experiment>/scores/rf3_metrics.csv
  work/<experiment>/scores/rf3_pae_vs_plddt.png
  work/<experiment>/scores/rf3_ranked_plddt.png

Then run:  python scripts/06_collect_best.py
"""
import sys
import os
import importlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
C = importlib.import_module(importlib.import_module("partial_diffusion").default_config())
sys.path.insert(0, str(C.LIB_ROOT))
from rf3_metrics import gather_rf3_metrics

C.make_workdirs()

# --- Gather metrics ---
df = gather_rf3_metrics(
    parent=str(C.RF3_DIR),
    binder=C.RF3_ENZYME_CHAIN,
    target_f=C.RF3_SUBSTRATE_CHAIN,   # primary: enzyme↔substrate (what we're optimising)
    target_g=C.RF3_HEME_CHAIN,        # secondary: enzyme↔heme (cofactor coordination)
    out_csv=str(C.SCORES_DIR / "rf3_metrics.csv"),
)

if df.empty:
    sys.exit(f"No .score files found under {C.RF3_DIR} — check that RF3 jobs completed.")

df = df.rename(columns={
    "best_binder_plddt": "enzyme_plddt",
    "AF_best_min_pae":   "substrate_min_pae",
    "AF_ipsae_at_best":  "substrate_ipsae",
    "AG_best_min_pae":   "heme_min_pae",
    "AG_ipsae_at_best":  "heme_ipsae",
})

n_pass = ((df["enzyme_plddt"]    > C.PLDDT_CUT) &
          (df["substrate_min_pae"] < C.PAE_CUT) &
          (df["substrate_ipsae"]   > C.IPSAE_CUT)).sum()

print(f"\n{len(df)} designs scored — {n_pass} pass all thresholds")
print(f"  pLDDT > {C.PLDDT_CUT}  |  PAE < {C.PAE_CUT} Å  |  ipSAE > {C.IPSAE_CUT}")

# --- Plots (saved to disk; no display needed on HPC) ---
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    x = df["substrate_min_pae"].to_numpy(float)
    y = df["enzyme_plddt"].to_numpy(float)
    c = df["substrate_ipsae"].to_numpy(float)
    mask = np.isfinite(x) & np.isfinite(y) & np.isfinite(c)

    fig, ax = plt.subplots(figsize=(7, 5))
    sc = ax.scatter(x[mask], y[mask], c=c[mask], s=20, alpha=0.85,
                    linewidths=0, cmap="viridis", vmin=0, vmax=1)
    ax.axvline(C.PAE_CUT,   color="k", lw=0.9, ls="--", alpha=0.6)
    ax.axhline(C.PLDDT_CUT, color="k", lw=0.9, ls="--", alpha=0.6)
    ax.set_xlabel("Enzyme–substrate PAE (Å)  [lower = better]")
    ax.set_ylabel("Enzyme pLDDT  [higher = better]")
    ax.set_title(f"RF3 — PAE vs pLDDT  (n={len(df)})")
    ax.set_xlim(left=0)
    ax.set_ylim(0, 1.0)
    ax.grid(True, linestyle=":", linewidth=0.6, alpha=0.5)
    fig.colorbar(sc, ax=ax).set_label("substrate ipSAE  [higher = better]")
    fig.tight_layout()
    pae_png = C.SCORES_DIR / "rf3_pae_vs_plddt.png"
    fig.savefig(pae_png, dpi=150)
    plt.close()
    print(f"Plot -> {pae_png}")

    ranked = df.sort_values("enzyme_plddt", ascending=False).reset_index(drop=True)
    fig2, ax2 = plt.subplots(figsize=(8, 4))
    ax2.scatter(ranked.index, ranked["enzyme_plddt"], alpha=0.8, s=20)
    ax2.axhline(C.PLDDT_CUT, color="tomato", ls="--",
                label=f"threshold ({C.PLDDT_CUT})")
    ax2.set_xlabel("design rank")
    ax2.set_ylabel("enzyme_plddt")
    ax2.set_title("RF3 pLDDT — ranked designs")
    ax2.legend()
    fig2.tight_layout()
    rank_png = C.SCORES_DIR / "rf3_ranked_plddt.png"
    fig2.savefig(rank_png, dpi=150)
    plt.close()
    print(f"Plot -> {rank_png}")

except ImportError:
    print("matplotlib not available — skipping plots (metrics CSV still written).")

print(f"\n--- SUMMARY ---")
print(f"  Designs scored  : {len(df)}")
print(f"  Passing all cuts: {n_pass}  (pLDDT>{C.PLDDT_CUT}, PAE<{C.PAE_CUT}Å, ipSAE>{C.IPSAE_CUT})")
print(f"  Metrics CSV     : {C.SCORES_DIR}/rf3_metrics.csv")
print(f"  Plots           : {C.SCORES_DIR}/rf3_pae_vs_plddt.png")
print(f"                    {C.SCORES_DIR}/rf3_ranked_plddt.png")
if n_pass == 0:
    print(f"\n  WARNING: 0 designs passed — consider relaxing thresholds in config.py:")
    print(f"    PLDDT_CUT = {C.PLDDT_CUT}  (try 0.70)")
    print(f"    PAE_CUT   = {C.PAE_CUT}   (try 12.0)")
    print(f"    IPSAE_CUT = {C.IPSAE_CUT}  (try 0.40)")
print(f"\nNext:  python partial_diffusion/scripts/06_collect_best.py")
