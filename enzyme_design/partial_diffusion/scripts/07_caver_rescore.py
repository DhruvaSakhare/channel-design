#!/usr/bin/env python3
"""
07_caver_rescore.py — measure the channel in every design and rank by how much
it actually opened, relative to the parent enzyme.

This is the step that answers "did it go up?". Up to here the pipeline ranks by
pLDDT (06_collect_best.py), which selects for designs that fold LIKE THE PARENT
— exactly the wrong pressure if the point was to change the channel. A design
can pass every confidence gate and still have a channel narrower than the one
you started with.

Input : <WORK>/best_designs/*.cif   (from 06_collect_best.py)
        the parent baseline written by 00_caver_channel.py
Output: <WORK>/scores/caver_rescore.csv   — every design, ranked by delta
        <WORK>/best_designs/widened/      — only the designs that actually opened

Usage
-----
    # baseline path comes from 00_caver_channel.py
    python partial_diffusion/scripts/07_caver_rescore.py \
        --baseline inputs/PabUPO-II_withHEMEFE_and_NNBT_baseline.json

    # or measure the parent inline
    python partial_diffusion/scripts/07_caver_rescore.py \
        --parent inputs/PabUPO-II_withHEMEFE_and_NNBT.pdb

    # a different folder of structures
    python partial_diffusion/scripts/07_caver_rescore.py --designs /path/to/cifs --parent <pdb>

Note: RF3 output contains the heme, which is what CAVER anchors on. A design
whose heme did not survive the fold is reported as 'no heme' and skipped —
that is itself a red flag worth seeing.
"""
import argparse
import csv
import importlib
import json
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "lib"))
import caver_utils as cu  # noqa: E402

from paths import CIF_TO_PDB  # noqa: E402


def parse_args():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--designs", default=None,
                   help="Folder of design .cif/.pdb files (default: <WORK>/best_designs)")
    p.add_argument("--baseline", default=None,
                   help="Parent baseline JSON from 00_caver_channel.py")
    p.add_argument("--parent", default=None,
                   help="Parent PDB — measured inline if no --baseline given "
                        "(default: the config's INPUT_PDB)")
    p.add_argument("--out-dir", default=None,
                   help="Where to write results (default: <WORK>/scores)")
    p.add_argument("--work-dir", default=None,
                   help="Scratch dir for the CAVER runs (default: <out-dir>/caver_rescore)")
    p.add_argument("--max-length", type=float, default=25.0)
    p.add_argument("--max-curvature", type=float, default=1.5)
    p.add_argument("--probe-radius", type=float, default=None)
    p.add_argument("--keep-substrate", action="store_true",
                   help="Measure channels WITH the bound substrate. Default strips it. "
                        "RF3 folds enzyme+heme+substrate, so designs arrive holo while "
                        "crystal references are apo; a bound ligand costs ~0.45 A of "
                        "bottleneck radius, roughly 6x the spread between real structures. "
                        "Stripping keeps parent, designs and references comparable.")
    p.add_argument("--min-gain", type=float, default=0.0,
                   help="A design counts as widened when its bottleneck radius exceeds "
                        "the parent's by more than this (A, default: 0.0 — any gain)")
    p.add_argument("--limit", type=int, default=None,
                   help="Only process the first N designs (quick check)")
    return p.parse_args()


def load_config():
    """The run config, if we are on a machine set up for the pipeline."""
    try:
        return importlib.import_module(
            os.environ.get("PIPELINE_BASE_CONFIG", "partial_diffusion.config"))
    except Exception:
        return None


def to_pdb(struct, dest_dir):
    """Return a PDB path for a design, converting from CIF if needed."""
    struct = Path(struct)
    if struct.suffix == ".pdb":
        return struct
    dest = Path(dest_dir) / f"{struct.stem}.pdb"
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(CIF_TO_PDB.parent))
    import cif_to_pdb
    return dest if cif_to_pdb.convert(struct, dest) else None


def measure(pdb_path, work_dir, args):
    """CAVER one structure; return its best tunnel dict, or None."""
    out = cu.run_caver(pdb_path, work_dir, probe_radius=args.probe_radius,
                       strip=None if args.keep_substrate else "auto")
    if out is None:
        return None
    return cu.best_tunnel(out, max_length=args.max_length,
                          max_curvature=args.max_curvature)


def main():
    args = parse_args()
    if not cu.caver_available():
        sys.exit(f"CAVER is not runnable here — need java on PATH and {cu.CAVER_JAR}")

    C = load_config()

    # ── where things live ────────────────────────────────────────────────────
    if args.designs:
        designs_dir = Path(args.designs)
    elif C is not None:
        designs_dir = Path(C.BEST_DIR)
    else:
        sys.exit("Pass --designs (no pipeline config importable here).")

    if args.out_dir:
        out_dir = Path(args.out_dir)
    elif C is not None:
        out_dir = Path(C.SCORES_DIR)
    else:
        out_dir = designs_dir.parent / "scores"
    out_dir.mkdir(parents=True, exist_ok=True)

    work_root = Path(args.work_dir) if args.work_dir else out_dir / "caver_rescore"
    pdb_cache = work_root / "pdb"
    work_root.mkdir(parents=True, exist_ok=True)

    # ── parent baseline ──────────────────────────────────────────────────────
    mode = "holo" if args.keep_substrate else "apo"

    if args.baseline:
        base = json.loads(Path(args.baseline).read_text())
        parent_r = base["bottleneck_radius"]
        parent_name = base.get("structure", Path(args.baseline).stem)
        base_mode = base.get("measured")
        if base_mode and base_mode != mode:
            sys.exit(
                f"Baseline was measured {base_mode} but designs would be measured {mode}.\n"
                f"Comparing across those is meaningless — a bound substrate shifts the\n"
                f"bottleneck by far more than any design does. Either re-run\n"
                f"00_caver_channel.py {'--keep-substrate' if mode == 'holo' else ''} "
                f"to rebuild the baseline, or {'drop' if mode == 'holo' else 'add'} "
                f"--keep-substrate here.")
        print(f"Parent baseline : {parent_name}  bottleneck {parent_r:.3f} A "
              f"(from {args.baseline})")
    else:
        parent = args.parent or (C.INPUT_PDB if C is not None else None)
        if not parent:
            sys.exit("Pass --baseline or --parent.")
        parent = Path(parent)
        if not parent.exists():
            sys.exit(f"Parent structure not found: {parent}")
        print(f"Measuring parent: {parent.name} ...")
        t = measure(parent, work_root / "_parent", args)
        if t is None:
            sys.exit("Could not measure a channel in the parent — check the heme, "
                     "or loosen --max-length / --max-curvature.")
        parent_r = t["bottleneck_radius"]
        parent_name = parent.name
        print(f"Parent bottleneck : {parent_r:.3f} A")

    # ── designs ──────────────────────────────────────────────────────────────
    structures = sorted(
        [p for p in designs_dir.iterdir()
         if p.suffix in (".cif", ".pdb") and not p.name.startswith(".")])
    if not structures:
        sys.exit(f"No .cif/.pdb designs in {designs_dir}")
    if args.limit:
        structures = structures[:args.limit]

    print(f"\nMeasuring {len(structures)} design(s) from {designs_dir}")
    print(f"Target: bottleneck radius > {parent_r + args.min_gain:.3f} A\n")

    rows = []
    for i, struct in enumerate(structures, 1):
        stem = struct.stem
        pdb = to_pdb(struct, pdb_cache)
        if pdb is None:
            print(f"  [{i}/{len(structures)}] {stem:<45} conversion failed")
            rows.append({"design": stem, "status": "convert_failed"})
            continue

        t = measure(pdb, work_root / stem, args)
        if t is None:
            fe, _, _ = cu.find_heme_fe(pdb)
            reason = "no_heme" if fe is None else "no_tunnel"
            print(f"  [{i}/{len(structures)}] {stem:<45} {reason}")
            rows.append({"design": stem, "status": reason})
            continue

        delta = t["bottleneck_radius"] - parent_r
        widened = delta > args.min_gain
        rows.append({
            "design":            stem,
            "status":            "ok",
            "bottleneck_radius": round(t["bottleneck_radius"], 4),
            "parent_radius":     round(parent_r, 4),
            "delta_radius":      round(delta, 4),
            "pct_change":        round(100.0 * delta / parent_r, 1) if parent_r else "",
            "widened":           "yes" if widened else "no",
            "length":            round(t["length"], 3) if t["length"] else "",
            "throughput":        round(t["throughput"], 4) if t["throughput"] else "",
            "curvature":         round(t["curvature"], 3) if t["curvature"] else "",
            "tunnel":            t["tunnel"],
        })
        mark = "WIDER" if widened else "     "
        print(f"  [{i}/{len(structures)}] {stem:<45} {t['bottleneck_radius']:.3f} A  "
              f"({delta:+.3f}, {100.0 * delta / parent_r:+.1f}%)  {mark}")

    # ── output ───────────────────────────────────────────────────────────────
    ok = [r for r in rows if r.get("status") == "ok"]
    ok.sort(key=lambda r: -r["delta_radius"])
    failed = [r for r in rows if r.get("status") != "ok"]

    csv_path = out_dir / "caver_rescore.csv"
    fields = ["design", "status", "bottleneck_radius", "parent_radius",
              "delta_radius", "pct_change", "widened", "length", "throughput",
              "curvature", "tunnel"]
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(ok + failed)

    widened = [r for r in ok if r["widened"] == "yes"]
    if widened:
        wdir = designs_dir / "widened"
        wdir.mkdir(exist_ok=True)
        for r in widened:
            for cand in (designs_dir / f"{r['design']}.cif",
                         designs_dir / f"{r['design']}.pdb"):
                if cand.exists():
                    shutil.copy2(cand, wdir / cand.name)
                    break

    print(f"\n--- SUMMARY ---")
    print(f"  Parent            : {parent_name}  ({parent_r:.3f} A, measured {mode})")
    print(f"  Measured          : {len(ok)} / {len(structures)}")
    if failed:
        reasons = {}
        for r in failed:
            reasons[r["status"]] = reasons.get(r["status"], 0) + 1
        print(f"  Not measured      : {', '.join(f'{v} {k}' for k, v in reasons.items())}")
    print(f"  Widened           : {len(widened)} / {len(ok)}"
          f"  (> {parent_r + args.min_gain:.3f} A)")
    if ok:
        best = ok[0]
        print(f"  Best              : {best['design']}  {best['bottleneck_radius']:.3f} A "
              f"({best['delta_radius']:+.3f} A, {best['pct_change']:+.1f}%)")
        median = ok[len(ok) // 2]
        print(f"  Median            : {median['delta_radius']:+.3f} A")
    print(f"  Ranked CSV        : {csv_path}")
    if widened:
        print(f"  Widened designs   : {designs_dir / 'widened'}/")
    else:
        print(f"\n  NOTHING WIDENED. The run did not do what it was for. Check:")
        print(f"    - CHANNEL_PLACEHOLDER set? Without it RFD3 collapses the channel.")
        print(f"    - Are FLEXIBLE_RESIDUES the residues that actually line THIS tunnel?")
        print(f"      Re-derive them: 00_caver_channel.py <parent pdb>")
        print(f"    - MPNN_TEMPERATURE above 0.1, so sequences are not all identical?")


if __name__ == "__main__":
    main()
