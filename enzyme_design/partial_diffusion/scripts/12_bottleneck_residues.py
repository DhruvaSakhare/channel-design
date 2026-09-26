#!/usr/bin/env python3
"""
12_bottleneck_residues.py — what is actually blocking the channel, and which of
those residues were you allowed to change?

"The opening is wider but something is still obstructing it" is a diagnosable
statement: at the narrowest point of the tunnel, some specific atoms are what
make it narrow. This finds them, and — the useful part — reports whether each
was in FLEXIBLE_RESIDUES. A blocker that was NEVER flexible is the reason the
channel did not open further, and adding it to the list is a concrete next step.
A blocker that WAS flexible means the design chose to put something there
anyway, which is a different problem (and usually means the constriction is
backbone-limited, not sidechain-limited).

Also proposes an extended flexible set: every residue lining the tunnel within
a chosen radius, optionally restricted to a stretch along the tunnel axis, so
you can widen the mouth without freeing the whole protein.

Usage
-----
    # what's blocking a specific design
    python partial_diffusion/scripts/12_bottleneck_residues.py \\
        --caver-out <WORK>/scores/rescore20/caver_rescore/<design>/out

    # propose an extended flexible list from the parent, covering the outer
    # half of the tunnel (the mouth) with a more generous contact radius
    python partial_diffusion/scripts/12_bottleneck_residues.py \\
        --caver-out inputs/caver_PabUPO-II_withHEMEFE_and_NNBT/out \\
        --shell 5.0 --along 0.4 1.0 --propose
"""
import argparse
import importlib
import os
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "lib"))
import caver_utils as cu  # noqa: E402


def parse_args():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--caver-out", required=True,
                   help="A CAVER out/ directory (from 00_caver_channel.py or "
                        "07_caver_rescore.py's per-design work dirs)")
    p.add_argument("--structure", default=None,
                   help="PDB whose atoms to measure against. Default: the "
                        "canonically-staged structure.pdb sitting next to out/.")
    p.add_argument("--chain", default="A")
    p.add_argument("--shell", type=float, default=2.0,
                   help="Report residues with an atom within (tunnel radius + this) "
                        "of the axis, in A. Default 2.0: CAVER's R is the EMPTY "
                        "sphere radius, so a lining atom's CENTRE sits at about "
                        "R + its vdW radius (~1.7 A for carbon) — anything below "
                        "~1.8 finds nothing at all. Raise to 4-5 for second-shell "
                        "residues behind the lining.")
    p.add_argument("--along", type=float, nargs=2, metavar=("LO", "HI"), default=None,
                   help="Restrict to a fraction of the tunnel: 0=heme, 1=surface. "
                        "e.g. --along 0.4 1.0 for the outer half (the mouth).")
    p.add_argument("--flexible", default=None,
                   help="Comma-separated list or a *_flex.json. Default: the "
                        "config's FLEXIBLE_RESIDUES.")
    p.add_argument("--propose", action="store_true",
                   help="Print a ready-to-paste FLEXIBLE_RESIDUES list combining "
                        "the current set with everything found here")
    p.add_argument("--max-length", type=float, default=25.0)
    p.add_argument("--max-curvature", type=float, default=1.5)
    return p.parse_args()


def load_atoms(pdb_path, chain):
    """[(resnum, resname, atomname, xyz)] for protein atoms of one chain."""
    out = []
    with open(pdb_path) as f:
        for line in f:
            if not line.startswith("ATOM") or line[21] != chain:
                continue
            if line[16] not in (" ", "A"):
                continue
            name = line[12:16].strip()
            if name == "FE":            # the synthetic FEX marker
                continue
            try:
                num = int(line[22:26])
            except ValueError:
                continue
            out.append((num, line[17:20].strip(), name,
                        np.array([float(line[30:38]), float(line[38:46]),
                                  float(line[46:54])])))
    return out


def main():
    args = parse_args()
    caver_out = Path(args.caver_out)
    if not caver_out.exists():
        sys.exit(f"Not found: {caver_out}")

    structure = Path(args.structure) if args.structure else (
        caver_out.parent / "pdb" / cu.CANONICAL_PDB_NAME)
    if not structure.exists():
        sys.exit(f"No structure at {structure} — pass --structure explicitly.")

    # current flexible set
    flexible = set()
    if args.flexible:
        src = Path(args.flexible)
        if src.suffix == ".json" and src.exists():
            import json
            flexible = set(json.loads(src.read_text())["flexible_residues"])
        else:
            flexible = {int(x) for x in args.flexible.replace(" ", "").split(",") if x}
    else:
        try:
            C = importlib.import_module(
                os.environ.get("PIPELINE_BASE_CONFIG", "partial_diffusion.config"))
            flexible = set(getattr(C, "FLEXIBLE_RESIDUES", []))
        except Exception:
            pass

    tunnel = cu.best_tunnel(caver_out, max_length=args.max_length,
                            max_curvature=args.max_curvature)
    if tunnel is None:
        sys.exit("No tunnel passed the geometry filters in this CAVER output.")
    path = cu.read_tunnel_path(caver_out, tunnel["tunnel"])
    if not path:
        sys.exit("No tunnel path data.")

    pts = np.array([p[:3] for p in path])
    radii = np.array([p[3] for p in path])
    seg = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    frac = seg / seg[-1] if seg[-1] > 0 else seg

    atoms = load_atoms(structure, args.chain)
    if not atoms:
        sys.exit(f"No chain-{args.chain} protein atoms in {structure}")
    coords = np.array([a[3] for a in atoms])

    print(f"Structure : {structure}")
    print(f"Tunnel    : {tunnel['tunnel']}  bottleneck {tunnel['bottleneck_radius']:.3f} A, "
          f"length {tunnel['length']:.1f} A")
    print(f"Flexible  : {len(flexible)} residues currently free\n")

    # ── 1. what forms the bottleneck ─────────────────────────────────────────
    bi = int(np.argmin(radii))
    d = np.linalg.norm(coords - pts[bi], axis=1)
    near = sorted({(atoms[i][0], atoms[i][1], atoms[i][2], round(float(d[i]), 2))
                   for i in np.where(d <= radii[bi] + max(args.shell, 2.0))[0]},
                  key=lambda t: t[3])

    print(f"=== AT THE BOTTLENECK ({radii[bi]:.3f} A, "
          f"{frac[bi]*100:.0f}% along the tunnel) ===")
    if not near:
        print("  (nothing within range — try a larger --shell)")
    seen = set()
    for num, rname, aname, dist in near:
        if num in seen:
            continue
        seen.add(num)
        tag = "flexible" if num in flexible else "** NOT FLEXIBLE **"
        print(f"  {rname}{num:<4d} closest atom {aname:<4s} {dist:5.2f} A   {tag}")

    blockers_fixed = sorted(n for n in seen if n not in flexible)
    if blockers_fixed:
        print(f"\n  {len(blockers_fixed)} residue(s) at the constriction were NOT "
              f"free to change: {blockers_fixed}")
        print(f"  These are the direct candidates to add to FLEXIBLE_RESIDUES.")
    else:
        print(f"\n  Every residue at the constriction was already flexible.")
        print(f"  The design put something there anyway — which usually means the")
        print(f"  narrowing is backbone geometry, not sidechain bulk, so freeing")
        print(f"  more residues will not help as much as raising PARTIAL_T.")

    # ── 2. lining over a chosen stretch ──────────────────────────────────────
    lo, hi = args.along if args.along else (0.0, 1.0)
    sel = np.where((frac >= lo) & (frac <= hi))[0]
    lining = {}
    for i in sel:
        dd = np.linalg.norm(coords - pts[i], axis=1)
        for j in np.where(dd <= radii[i] + args.shell)[0]:
            num = atoms[j][0]
            if num not in lining or dd[j] < lining[num][1]:
                lining[num] = (atoms[j][1], float(dd[j]))

    label = f"{lo:.2f}-{hi:.2f} of tunnel" if args.along else "whole tunnel"
    print(f"\n=== LINING RESIDUES ({label}, within radius + {args.shell} A) ===")
    new = sorted(n for n in lining if n not in flexible)
    print(f"  total lining      : {len(lining)}")
    print(f"  already flexible  : {len(lining) - len(new)}")
    print(f"  NOT yet flexible  : {len(new)}  {new}")

    if args.propose:
        combined = sorted(flexible | set(lining))
        print(f"\n=== PROPOSED FLEXIBLE_RESIDUES ({len(combined)}) ===")
        print("FLEXIBLE_RESIDUES = [")
        for i in range(0, len(combined), 12):
            print("    " + ", ".join(str(r) for r in combined[i:i+12]) + ",")
        print("]")
        print(f"\n  Was {len(flexible)}, now {len(combined)} "
              f"(+{len(combined) - len(flexible)}).")
        print(f"  Freeing more residues means a bigger remodel and more chances to")
        print(f"  break the fold — the pLDDT/PAE/ipSAE pass rate is what tells you")
        print(f"  if you went too far. Re-derive CATRES/FIXED_ATOMS by passing this")
        print(f"  via --flexible to 00_submit_all.py rather than editing by hand.")


if __name__ == "__main__":
    main()
