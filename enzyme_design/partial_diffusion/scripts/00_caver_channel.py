#!/usr/bin/env python3
"""
00_caver_channel.py — derive the channel from the PARENT structure, before any
design work happens.

Runs CAVER on your input enzyme and writes three things:

  <stem>_flex.json       the channel-lining residues, in the same format
                         mark_flexible.py produces — so it feeds straight into
                         00_from_pymol.py and becomes FLEXIBLE_RESIDUES.
  <stem>_channel.pdb     the tunnel axis as a placeholder pseudo-ligand (see
                         --placeholder below).
  <stem>_baseline.json   the parent's bottleneck radius / length / throughput,
                         which 07_caver_rescore.py later compares designs
                         against. This is the "did it actually go up?" number.

Why derive the residues instead of picking them by hand: a hand-written
FLEXIBLE_RESIDUES list is a homology argument ("this substitutes AaeUPO F76").
CAVER measures the channel in YOUR structure. The two usually overlap, and
where they disagree the measurement is the one to trust.

Usage
-----
    python partial_diffusion/scripts/00_caver_channel.py inputs/PabUPO-II_withHEMEFE_and_NNBT.pdb

    # keep catalytic residues out of the flexible list (recommended)
    python partial_diffusion/scripts/00_caver_channel.py <pdb> --exclude 52,85,137,205,212,215,296,339

    # only residues that line the channel with a SIDECHAIN — the ones MPNN can
    # actually shrink. Backbone-only liners need RFD3 movement to change.
    python partial_diffusion/scripts/00_caver_channel.py <pdb> --sidechain-only

Then:
    python partial_diffusion/scripts/00_from_pymol.py <pdb> <stem>_flex.json \
        --experiment my_run_01 --your-name me
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "lib"))
import caver_utils as cu  # noqa: E402


def parse_args():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("pdb", help="Parent enzyme PDB (heme present, protein on chain A)")
    p.add_argument("--chain", default="A", help="Protein chain (default: A)")
    p.add_argument("--out-dir", default=None,
                   help="Where to write the JSON/PDB outputs (default: alongside the input PDB)")
    p.add_argument("--work-dir", default=None,
                   help="Where CAVER runs (default: <out-dir>/caver_<stem>)")
    p.add_argument("--exclude", default="",
                   help="Comma-separated residue numbers to keep OUT of the flexible list "
                        "(catalytic residues, disulfides)")
    p.add_argument("--sidechain-only", action="store_true",
                   help="Only residues lining the channel with a sidechain")
    p.add_argument("--probe-radius", type=float, default=None,
                   help="CAVER probe radius override (config default: 0.4)")
    p.add_argument("--substrate", default=None,
                   help="Substrate residue name to strip, e.g. UNL. Naming it is more "
                        "reliable than the default, which identifies the substrate by "
                        "elimination and so cannot tell a docked ligand from an "
                        "unfamiliar crystallographic one.")
    p.add_argument("--keep-substrate", action="store_true",
                   help="Measure the channel WITH the docked substrate in place. Default is "
                        "to strip it: a bound ligand narrows the tunnel by several times the "
                        "difference between real structures, so measuring holo "
                        "reports how much gap is left beside the ligand rather than how wide "
                        "the opening is. 07_caver_rescore.py defaults the same way, so parent "
                        "and designs stay comparable.")
    p.add_argument("--max-length", type=float, default=25.0,
                   help="Ignore tunnels longer than this (default: 25 A)")
    p.add_argument("--max-curvature", type=float, default=1.5,
                   help="Ignore tunnels more curved than this (default: 1.5)")
    p.add_argument("--placeholder-shrink", type=float, default=0.0,
                   help="Place channel-placeholder atoms only where the tunnel radius "
                        "exceeds this (A). Higher = placeholder marks only the already-wide "
                        "stretch, so RFD3 is pushed to open the narrow part rather than "
                        "freeze the current shape.")
    p.add_argument("--placeholder-spacing", type=float, default=1.5,
                   help="Minimum gap between placeholder atoms (default: 1.5 A)")
    return p.parse_args()


def main():
    args = parse_args()
    pdb = Path(args.pdb).resolve()
    if not pdb.exists():
        sys.exit(f"Not found: {pdb}")
    if not cu.caver_available():
        sys.exit("CAVER is not runnable here — need java on PATH and "
                 f"{cu.CAVER_JAR}\n"
                 "\n"
                 "CAVER is GPLv3 and is not bundled with this repository.\n"
                 "Get it with:  ./scripts/fetch_third_party.sh\n"
                 "or point $CAVER_HOME at a copy you already have.\n"
                 "A JDK comes with:  conda env create -f envs/docking.yml")

    stem    = pdb.stem
    out_dir = Path(args.out_dir).resolve() if args.out_dir else pdb.parent
    work    = Path(args.work_dir).resolve() if args.work_dir else out_dir / f"caver_{stem}"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Structure : {pdb}")
    print(f"CAVER run : {work}")
    print("Running CAVER (this takes a minute)...")

    strip = None if args.keep_substrate else "auto"
    if strip:
        subs = cu.substrate_resnames(pdb, substrate=args.substrate)
        if subs:
            print(f"Substrate : {', '.join(sorted(subs))} — stripped (measuring apo)")

    caver_out = cu.run_caver(pdb, work, probe_radius=args.probe_radius,
                             quiet=False, strip=strip, substrate=args.substrate)
    if caver_out is None:
        sys.exit("CAVER did not produce usable output — see the log above.")

    tunnel = cu.best_tunnel(caver_out,
                            max_length=args.max_length,
                            max_curvature=args.max_curvature)
    if tunnel is None:
        sys.exit(f"No tunnel passed the geometry filters "
                 f"(length <= {args.max_length} A, curvature <= {args.max_curvature}). "
                 f"Loosen them, or check that the heme is where you think it is.")

    print(f"\nBest channel — tunnel {tunnel['tunnel']} (cluster {tunnel['cluster']})")
    print(f"  bottleneck radius : {tunnel['bottleneck_radius']:.3f} A   <- the number to beat")
    print(f"  length            : {tunnel['length']:.2f} A")
    print(f"  throughput        : {tunnel['throughput']:.3f}")
    print(f"  curvature         : {tunnel['curvature']:.2f}")

    # ── lining residues → flexible list ──────────────────────────────────────
    keep = cu.protein_resnums(pdb, args.chain)
    try:
        cluster = int(tunnel["cluster"])
    except (TypeError, ValueError):
        cluster = 1
    lining = cu.read_lining_residues(caver_out, cluster, keep_resnums=keep)

    excluded = {int(x) for x in args.exclude.replace(" ", "").split(",") if x}
    flexible = set(lining["sidechain"])
    if not args.sidechain_only:
        flexible |= set(lining["backbone"])
    dropped  = sorted(flexible & excluded)
    flexible = sorted(flexible - excluded)

    print(f"\nChannel-lining residues on chain {args.chain}:")
    print(f"  sidechain-lining ({len(lining['sidechain'])}) : {lining['sidechain']}")
    print(f"  backbone-only    ({len(lining['backbone'])}) : {lining['backbone']}")
    if dropped:
        print(f"  excluded by --exclude          : {dropped}")
    print(f"  -> FLEXIBLE_RESIDUES ({len(flexible)}) : {flexible}")

    if not flexible:
        sys.exit("Nothing left after filtering — check --exclude and --sidechain-only.")

    flex_path = out_dir / f"{stem}_flex.json"
    flex_path.write_text(json.dumps({
        "input_pdb": pdb.name,
        "chain": args.chain,
        "flexible_residues": flexible,
        "source": "caver",
        "sidechain_lining": lining["sidechain"],
        "backbone_lining": lining["backbone"],
        "excluded": sorted(excluded),
    }, indent=2))

    # ── baseline geometry, for the after-the-fact comparison ─────────────────
    baseline_path = out_dir / f"{stem}_baseline.json"
    baseline_path.write_text(json.dumps({
        "structure": pdb.name,
        "tunnel": tunnel["tunnel"],
        "cluster": tunnel["cluster"],
        "bottleneck_radius": tunnel["bottleneck_radius"],
        "length": tunnel["length"],
        "throughput": tunnel["throughput"],
        "curvature": tunnel["curvature"],
        "measured": "holo" if args.keep_substrate else "apo",
    }, indent=2))

    # ── channel placeholder ──────────────────────────────────────────────────
    path_points = cu.read_tunnel_path(caver_out, tunnel["tunnel"])
    chan_path, n_atoms = cu.write_channel_placeholder(
        path_points, out_dir / f"{stem}_channel.pdb",
        spacing=args.placeholder_spacing, shrink=args.placeholder_shrink)

    print(f"\nWrote:")
    print(f"  {flex_path}")
    print(f"  {baseline_path}")
    if chan_path:
        print(f"  {chan_path}   ({n_atoms} placeholder atoms, resname TUN chain D)")
    else:
        print(f"  (no placeholder written — no tunnel points above "
              f"--placeholder-shrink {args.placeholder_shrink})")

    print(f"\nNext:")
    print(f"  python partial_diffusion/scripts/00_from_pymol.py \\")
    print(f"      {pdb} {flex_path} --experiment <name> --your-name <you>")
    print(f"\nAfter the run finishes, compare designs against this baseline:")
    print(f"  python partial_diffusion/scripts/07_caver_rescore.py --baseline {baseline_path}")


if __name__ == "__main__":
    main()
