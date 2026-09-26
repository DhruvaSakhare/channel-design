#!/usr/bin/env python3
"""
10_plot_channels.py — overlay channel profiles: parent vs designs.

A bottleneck radius is one number per structure. This plots the whole channel —
radius at every point along the tunnel axis, from the heme iron out to solvent —
so you can see WHERE a design opened up, not just that it did. A design can gain
0.1 A at the bottleneck and be unchanged everywhere else, or widen along the
whole bore; those are different results and the single number hides it.

Reuses the CAVER runs that 07_caver_rescore.py already did, so this is fast —
no re-running CAVER unless you point it somewhere without existing output.

Usage
-----
    # after 07_caver_rescore.py --out-dir /tmp/rescore20
    python partial_diffusion/scripts/10_plot_channels.py \\
        --rescore-dir /tmp/rescore20 \\
        --parent-caver inputs/caver_PabUPO-II_withHEMEFE_and_NNBT/out \\
        --out channels.png

    # just the top 5
    python partial_diffusion/scripts/10_plot_channels.py --rescore-dir /tmp/rescore20 --top 5
"""
import argparse
import csv
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

try:
    from scipy.ndimage import gaussian_filter1d
except ImportError:
    gaussian_filter1d = None


def _smooth(r, sigma):
    """Display-only smoothing. Edge values are held (mode='nearest') so the
    heme-end and exit-end radii are not dragged toward zero."""
    if not sigma or gaussian_filter1d is None or len(r) < 3:
        return r
    return gaussian_filter1d(r, sigma=sigma, mode="nearest")

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
                   help="Output dir from 07_caver_rescore.py (holds caver_rescore.csv "
                        "and the per-design caver_rescore/<stem>/ work dirs)")
    p.add_argument("--parent-caver", default=None,
                   help="Parent's CAVER out/ dir (from 00_caver_channel.py). "
                        "Omit to plot designs only.")
    p.add_argument("--top", type=int, default=8, help="How many designs to draw (default 8)")
    p.add_argument("--mirror", action="store_true",
                   help="Draw R both positive and negative, so the plot reads as a "
                        "cross-section through the bore rather than a line graph "
                        "(the style extract_tunnel_R.py uses).")
    p.add_argument("--normalize", action="store_true",
                   help="Put distance on a 0-1 axis (0=heme, 1=exit) so tunnels of "
                        "different lengths line up. Without this the x-axis is "
                        "absolute Angstroms and a longer tunnel simply runs further "
                        "right — better for seeing real length differences.")
    p.add_argument("--ylim", type=float, default=None,
                   help="Y-axis limit (default: fit the data)")
    p.add_argument("--smooth", type=float, default=0.0,
                   help="Gaussian smoothing sigma in SAMPLE POINTS (try 1-2). CAVER "
                        "samples the axis every ~0.5 A, so small wobbles in the tunnel "
                        "path show up as kinks. This smooths the DISPLAY only — the "
                        "bottleneck numbers in the legend are always from the raw data, "
                        "so smoothing can never flatter a design's reported radius.")
    p.add_argument("--out", default="channels.png")
    p.add_argument("--max-length", type=float, default=25.0)
    p.add_argument("--max-curvature", type=float, default=1.5)
    return p.parse_args()


def profile(caver_out, max_length, max_curvature):
    """(distance_along_axis, radius) for a CAVER out/ dir, or None."""
    t = cu.best_tunnel(caver_out, max_length=max_length, max_curvature=max_curvature)
    if t is None:
        return None
    path = cu.read_tunnel_path(caver_out, t["tunnel"])
    if not path:
        return None
    pts = np.array([p[:3] for p in path])
    r = np.array([p[3] for p in path])
    # cumulative distance along the axis, starting at the heme end
    d = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    return d, r


def main():
    args = parse_args()
    rescore_dir = Path(args.rescore_dir)
    csv_path = rescore_dir / "caver_rescore.csv"
    if not csv_path.exists():
        sys.exit(f"No caver_rescore.csv in {rescore_dir} — run 07_caver_rescore.py first.")

    rows = [r for r in csv.DictReader(open(csv_path)) if r.get("status") == "ok"]
    if not rows:
        sys.exit("No successfully measured designs in the CSV.")
    rows.sort(key=lambda r: -_delta(r))
    rows = rows[:args.top]

    fig, ax = plt.subplots(figsize=(10, 5.5))

    parent_r = None
    if args.parent_caver:
        pp = profile(Path(args.parent_caver), args.max_length, args.max_curvature)
        if pp is None:
            print(f"WARNING: no usable tunnel in {args.parent_caver}")
        else:
            d, r = pp
            parent_r = float(r.min())
            x = d / d[-1] if (args.normalize and d[-1] > 0) else d
            rs = _smooth(r, args.smooth)
            ax.plot(x, rs, color="black", linewidth=3, zorder=10,
                    label=f"parent  (tunnel 1, {d[-1]:.1f} A, bneck {parent_r:.3f} A)")
            if args.mirror:
                ax.plot(x, -rs, color="black", linewidth=3, zorder=10)

    cmap = plt.get_cmap("viridis")
    drawn = 0
    for i, row in enumerate(rows):
        stem = row["design"]
        out_dir = rescore_dir / "caver_rescore" / stem / "out"
        if not out_dir.exists():
            print(f"  (no CAVER output for {stem})")
            continue
        pr = profile(out_dir, args.max_length, args.max_curvature)
        if pr is None:
            continue
        d, r = pr
        short = stem.replace("rfd3_partial_input_partial_rfd3_0_", "")
        col = cmap(i / max(1, len(rows) - 1))
        x = d / d[-1] if (args.normalize and d[-1] > 0) else d
        rs = _smooth(r, args.smooth)
        ax.plot(x, rs, color=col, linewidth=1.4, alpha=0.85,
                label=f"{short}  ({d[-1]:.1f} A, {float(row['bottleneck_radius']):.3f}, "
                      f"{_delta(row):+.3f})")
        if args.mirror:
            ax.plot(x, -rs, color=col, linewidth=1.4, alpha=0.85)
        drawn += 1

    if not drawn:
        sys.exit("Nothing to plot — no CAVER work dirs found under "
                 f"{rescore_dir / 'caver_rescore'}")

    if args.mirror:
        ax.axhline(0, color="black", linestyle="--", linewidth=0.7)
        if args.ylim:
            ax.set_ylim(-args.ylim, args.ylim)
    else:
        ax.axhline(1.4, color="grey", linestyle=":", linewidth=1,
                   label="~H2O probe radius (1.4 A)")
        if parent_r is not None:
            ax.axhline(parent_r, color="black", linestyle="--", linewidth=0.8, alpha=0.5)
        ax.set_ylim(0, args.ylim if args.ylim else None)

    ax.set_xlabel("Normalized distance (0 = heme, 1 = exit)" if args.normalize
                  else "Distance along tunnel from heme Fe (A)")
    ax.set_ylabel("Tunnel radius R (A)")
    ax.set_title(f"Substrate channel profile — parent vs top {drawn} designs")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=7, loc="upper left", bbox_to_anchor=(1.01, 1.0), borderaxespad=0)
    fig.tight_layout()
    fig.savefig(args.out, dpi=160, bbox_inches="tight")
    print(f"\nSaved {args.out}  ({drawn} design(s) + parent)")
    print("The left edge is the heme; the bottleneck is usually there. A design")
    print("that only rises on the right widened the exit, not the constriction.")


if __name__ == "__main__":
    main()
