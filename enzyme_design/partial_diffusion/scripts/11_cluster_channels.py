#!/usr/bin/env python3
"""
11_cluster_channels.py — cluster designs by channel SHAPE, not just bottleneck.

Same idea as channel_discovery/caver_pipeline/cluster_tunnels.py: resample each
tunnel's radius profile onto a normalized distance axis [0,1] so tunnels of
different lengths are comparable, then hierarchically cluster the profiles and
plot each cluster's members together.

Why a separate script instead of pointing cluster_tunnels.py at best_designs/:
that script consumes run_batch.py's output, and run_batch.py (a) never strips
the docked substrate, so RF3 designs are measured holo while the reference
crystals are apo — a systematic offset several times the real spread between
structures, and (b) stages every structure under its own filename, which
CAVER's tunnel search is measurably sensitive to. This reads the CAVER runs
07_caver_rescore.py already
did, which are apo and canonically staged, so the comparison is clean and no
CAVER re-run is needed.

What the clusters mean: a bottleneck radius is one number. Two designs can share
it while being shaped completely differently — one narrow only at the heme, one
narrow throughout. Clustering on the whole profile separates those, so you can
see whether your designs found one solution or several.

Usage
-----
    python partial_diffusion/scripts/11_cluster_channels.py \\
        --rescore-dir /tmp/rescore20 \\
        --parent-caver inputs/caver_PabUPO-II_withHEMEFE_and_NNBT/out \\
        --n-clusters 4 --out-dir channel_clusters
"""
import argparse
import csv
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.cluster.hierarchy import dendrogram, linkage, fcluster

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "lib"))
import caver_utils as cu  # noqa: E402


def _delta(row):
    """07_caver_rescore.py writes 'delta_radius'; tolerate 'delta' too."""
    for k in ("delta_radius", "delta"):
        if k in row and row[k] not in (None, ""):
            return float(row[k])
    raise KeyError("no delta_radius/delta column in caver_rescore.csv")


def parse_args():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--rescore-dir", required=True,
                   help="07_caver_rescore.py output dir (has caver_rescore.csv + work dirs)")
    p.add_argument("--parent-caver", default=None,
                   help="Parent's CAVER out/ dir — drawn on every cluster panel for reference")
    p.add_argument("--n-clusters", type=int, default=4)
    p.add_argument("--n-points", type=int, default=100,
                   help="Resampling resolution along the normalized axis (default 100)")
    p.add_argument("--top", type=int, default=None,
                   help="Only cluster the N widest designs (default: all measured)")
    p.add_argument("--out-dir", default="channel_clusters")
    p.add_argument("--max-length", type=float, default=25.0)
    p.add_argument("--max-curvature", type=float, default=1.5)
    return p.parse_args()


def profile(caver_out, max_length, max_curvature):
    t = cu.best_tunnel(caver_out, max_length=max_length, max_curvature=max_curvature)
    if t is None:
        return None
    path = cu.read_tunnel_path(caver_out, t["tunnel"])
    if len(path) < 3:
        return None
    pts = np.array([p[:3] for p in path])
    r = np.array([p[3] for p in path])
    d = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    return d, r


def resample(d, r, n):
    """Radius on a normalized [0,1] distance axis, so different-length tunnels
    can be compared point-for-point."""
    if d[-1] <= 0:
        return None
    return np.interp(np.linspace(0, 1, n), d / d[-1], r)


def main():
    args = parse_args()
    rescore_dir = Path(args.rescore_dir)
    csv_path = rescore_dir / "caver_rescore.csv"
    if not csv_path.exists():
        sys.exit(f"No caver_rescore.csv in {rescore_dir}")

    rows = [r for r in csv.DictReader(open(csv_path)) if r.get("status") == "ok"]
    rows.sort(key=lambda r: -_delta(r))
    if args.top:
        rows = rows[:args.top]
    if len(rows) < 2:
        sys.exit(f"Need at least 2 measured designs to cluster (got {len(rows)}).")

    names, profiles, deltas, radii = [], [], [], []
    for row in rows:
        out_dir = rescore_dir / "caver_rescore" / row["design"] / "out"
        if not out_dir.exists():
            continue
        pr = profile(out_dir, args.max_length, args.max_curvature)
        if pr is None:
            continue
        rs = resample(*pr, args.n_points)
        if rs is None:
            continue
        names.append(row["design"].replace("rfd3_partial_input_partial_rfd3_0_", ""))
        profiles.append(rs)
        deltas.append(_delta(row))
        radii.append(float(row["bottleneck_radius"]))

    if len(profiles) < 2:
        sys.exit(f"Only {len(profiles)} usable profile(s) — nothing to cluster.")

    X = np.array(profiles)
    n_clusters = min(args.n_clusters, len(X))
    Z = linkage(X, method="average", metric="euclidean")
    labels = fcluster(Z, n_clusters, criterion="maxclust")

    parent_prof = None
    if args.parent_caver:
        pp = profile(Path(args.parent_caver), args.max_length, args.max_curvature)
        if pp is not None:
            parent_prof = resample(*pp, args.n_points)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    x = np.linspace(0, 1, args.n_points)

    # ── dendrogram ───────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(max(8, len(names) * 0.28), 5))
    dendrogram(Z, labels=names, ax=ax, leaf_rotation=90, leaf_font_size=6,
               color_threshold=Z[-(n_clusters - 1), 2] if n_clusters > 1 else 0)
    ax.set_ylabel("profile distance")
    ax.set_title(f"Channel-shape clustering ({len(names)} designs)")
    fig.tight_layout()
    fig.savefig(out_dir / "dendrogram.png", dpi=160, bbox_inches="tight")
    plt.close(fig)

    # ── per-cluster profile panels ───────────────────────────────────────────
    ncol = min(n_clusters, 3)
    nrow = int(np.ceil(n_clusters / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(5.2 * ncol, 3.8 * nrow),
                             squeeze=False, sharey=True)
    cmap = plt.get_cmap("tab10")
    for c in range(1, n_clusters + 1):
        ax = axes[(c - 1) // ncol][(c - 1) % ncol]
        idx = np.where(labels == c)[0]
        for i in idx:
            ax.plot(x, X[i], color=cmap((c - 1) % 10), alpha=0.55, linewidth=1)
        if len(idx):
            ax.plot(x, X[idx].mean(axis=0), color=cmap((c - 1) % 10),
                    linewidth=2.6, label=f"cluster mean (n={len(idx)})")
        if parent_prof is not None:
            ax.plot(x, parent_prof, color="black", linewidth=2, linestyle="--",
                    label="parent")
        ax.axhline(1.4, color="grey", linestyle=":", linewidth=0.8)
        med = np.median([deltas[i] for i in idx]) if len(idx) else float("nan")
        ax.set_title(f"cluster {c}  (n={len(idx)}, median Δ {med:+.3f} Å)", fontsize=10)
        ax.set_xlabel("normalized distance from heme →  surface")
        ax.grid(alpha=0.25)
        ax.legend(fontsize=7)
    axes[0][0].set_ylabel("tunnel radius R (Å)")
    for j in range(n_clusters, nrow * ncol):
        axes[j // ncol][j % ncol].axis("off")
    fig.tight_layout()
    fig.savefig(out_dir / "cluster_profiles.png", dpi=160, bbox_inches="tight")
    plt.close(fig)

    # ── assignments ──────────────────────────────────────────────────────────
    with open(out_dir / "cluster_assignments.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["design", "cluster", "bottleneck_radius", "delta_radius"])
        for n, c, rad, dl in zip(names, labels, radii, deltas):
            w.writerow([n, int(c), f"{rad:.4f}", f"{dl:+.4f}"])

    print(f"Clustered {len(names)} designs into {n_clusters} shape groups\n")
    for c in range(1, n_clusters + 1):
        idx = np.where(labels == c)[0]
        if not len(idx):
            continue
        print(f"  cluster {c}: n={len(idx):3d}  "
              f"median bottleneck {np.median([radii[i] for i in idx]):.3f} A  "
              f"median Δ {np.median([deltas[i] for i in idx]):+.3f} A")
    print(f"\n  {out_dir}/dendrogram.png")
    print(f"  {out_dir}/cluster_profiles.png")
    print(f"  {out_dir}/cluster_assignments.csv")


if __name__ == "__main__":
    main()
