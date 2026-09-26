#!/usr/bin/env python3
"""
Stage 1.5 — CAVER filter: don't waste MPNN+RF3 on backbones that already
collapsed the channel.

Runs between 02_rfd3_process.py (structural quality: chain breaks, clashes)
and 03_mpnn_submit.py. Same principle as 08_probe_channel.py's --pilot gate,
just applied to a whole batch instead of one test backbone: RFD3 backbone
width is a NECESSARY condition — if RFD3 already squeezed the channel shut,
no sequence design reopens it, so there's no reason to spend GPU (MPNN, then
RF3) finding that out. CAVER runs on cheap CPU; MPNN/RF3 run on expensive GPU.

NOT sufficient, though: a backbone that measures fine here can still end up
narrow after MPNN redesigns the sequence and RF3 refolds from scratch — RF3
does not just place sidechains on this fixed backbone, it refolds everything.
So the bar here is deliberately low ("not meaningfully narrower than the
parent"), not a strict ranking — that's what 07_caver_rescore.py is for, on
real folded designs at the end.

Reads whichever backbone set 03_mpnn_submit.py would otherwise have used
(diffusion_out/passing/ if present, else diffusion_out/) and, if at least one
backbone passes, writes the survivors' .cif.gz + sidecar .json into a widened/
subfolder there. 03_mpnn_submit.py prefers widened/ if it exists.

Fails OPEN, not closed: if the baseline is missing, CAVER isn't runnable, or
NOTHING survives the filter, this prints why and does not create widened/ —
03_mpnn_submit.py then falls through to the unfiltered tier, exactly the
behaviour without this script. This runs unattended inside an LSF job chain,
so a filter stage must never be able to silently kill the whole pipeline.

Usage
-----
    python partial_diffusion/scripts/02b_caver_filter.py
    python partial_diffusion/scripts/02b_caver_filter.py --baseline <path> --tolerance 0.05
"""
import argparse
import csv
import glob
import gzip
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
    p.add_argument("--baseline", default=None,
                   help="Parent baseline JSON. Default: auto-discovered next to "
                        "INPUT_PDB, same name 00_caver_channel.py writes.")
    p.add_argument("--tolerance", type=float, default=0.05,
                   help="A backbone passes if its bottleneck radius is within this "
                        "many A of the parent's, or wider (default 0.05). "
                        "Deliberately permissive — this is a cheap first cut, not "
                        "the final ranking.")
    p.add_argument("--max-length", type=float, default=25.0)
    p.add_argument("--max-curvature", type=float, default=1.5)
    p.add_argument("--limit", type=int, default=None,
                   help="Only check the first N backbones (quick test)")
    return p.parse_args()


def to_pdb(struct, dest_dir):
    """.cif.gz -> plain PDB, same conversion 07/08 use."""
    struct = Path(struct)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = struct.name
    if name.endswith(".cif.gz"):
        cif = dest_dir / name[:-3]
        with gzip.open(struct, "rb") as gz, open(cif, "wb") as out:
            shutil.copyfileobj(gz, out)
        struct = cif
    dest = dest_dir / f"{struct.stem}.pdb"
    sys.path.insert(0, str(CIF_TO_PDB.parent))
    import cif_to_pdb
    return dest if cif_to_pdb.convert(struct, dest) else None


def main():
    args = parse_args()
    C = importlib.import_module(os.environ.get("PIPELINE_BASE_CONFIG", "partial_diffusion.config"))
    C.make_workdirs()

    if not cu.caver_available():
        print("CAVER not runnable here (need java + caver.jar) — "
              "skipping the channel filter, MPNN will use the unfiltered backbones.")
        return

    # ── baseline: same auto-discovery convention as the MSA path in config.py ──
    baseline_path = Path(args.baseline) if args.baseline else (
        Path(C.INPUT_PDB).parent / f"{Path(C.INPUT_PDB).stem}_baseline.json")
    if not baseline_path.exists():
        print(f"No baseline at {baseline_path} — skipping the channel filter.")
        print(f"  Generate one with: python partial_diffusion/scripts/"
              f"00_caver_channel.py {C.INPUT_PDB}")
        return
    baseline = json.loads(baseline_path.read_text())
    parent_r = baseline["bottleneck_radius"]
    base_mode = baseline.get("measured", "apo")
    print(f"Baseline: {parent_r:.3f} A (measured {base_mode}, from {baseline_path})")

    # ── same 2-tier fallback 03_mpnn_submit.py uses, so we filter whatever it
    #    would otherwise have read ──────────────────────────────────────────
    passing_dir = C.DIFFUSION_DIR / "passing"
    passing = sorted(glob.glob(str(passing_dir / "*.cif.gz")))
    tier_dir = passing_dir if passing else C.DIFFUSION_DIR
    structures = passing or sorted(glob.glob(str(C.DIFFUSION_DIR / "*.cif.gz")))

    if not structures:
        print(f"No backbones found in {C.DIFFUSION_DIR} — nothing to filter "
              f"(RFD3 may not have finished).")
        return
    if args.limit:
        structures = structures[:args.limit]

    print(f"Checking {len(structures)} backbone(s) from {tier_dir} "
          f"(tolerance {args.tolerance} A)\n")

    work = C.SCORES_DIR / "caver_filter_work"
    pdb_cache = work / "pdb"
    rows, kept = [], []

    for i, struct in enumerate(sorted(structures), 1):
        struct = Path(struct)
        stem = struct.name[:-len(".cif.gz")]
        pdb = to_pdb(struct, pdb_cache)
        if pdb is None:
            print(f"  [{i}/{len(structures)}] {stem:<40s} conversion failed")
            rows.append({"backbone": stem, "status": "convert_failed"})
            continue

        t = cu.best_tunnel(
            cu.run_caver(pdb, work / stem, strip=None if base_mode == "holo" else "auto"),
            max_length=args.max_length, max_curvature=args.max_curvature)
        if t is None:
            fe, _, _ = cu.find_heme_fe(pdb)
            reason = "no_heme" if fe is None else "no_tunnel"
            print(f"  [{i}/{len(structures)}] {stem:<40s} {reason}")
            rows.append({"backbone": stem, "status": reason})
            continue

        r = t["bottleneck_radius"]
        delta = r - parent_r
        passed = delta >= -args.tolerance
        rows.append({
            "backbone": stem, "status": "ok",
            "bottleneck_radius": round(r, 4), "parent_radius": round(parent_r, 4),
            "delta": round(delta, 4), "kept": "yes" if passed else "no",
        })
        if passed:
            kept.append(struct)
        print(f"  [{i}/{len(structures)}] {stem:<40s} {r:.3f} A  "
              f"({delta:+.3f})  {'KEEP' if passed else 'drop'}")

    csv_path = C.DIFFUSION_DIR / "caver_filter.csv"
    fields = ["backbone", "status", "bottleneck_radius", "parent_radius", "delta", "kept"]
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    print(f"\n--- SUMMARY ---")
    print(f"  Checked : {len(structures)}")
    print(f"  Kept    : {len(kept)}")
    print(f"  Log     : {csv_path}")

    if not kept:
        print(f"\n  NOTHING passed the filter — not writing widened/. "
              f"MPNN will use the unfiltered {tier_dir.name}/ instead, same as "
              f"if this script hadn't run. This usually means PARTIAL_T needs "
              f"raising, or FLEXIBLE_RESIDUES doesn't target the right tunnel — "
              f"see 08_probe_channel.py's advice on a single backbone first.")
        return

    widened_dir = tier_dir / "widened"
    widened_dir.mkdir(exist_ok=True)
    copied = 0
    for struct in kept:
        for src in (struct, struct.with_suffix("").with_suffix(".json")):
            if src.exists():
                dst = widened_dir / src.name
                if not dst.exists():
                    shutil.copy2(src, dst)
                    copied += 1
    print(f"  Copied {copied} file(s) -> {widened_dir}/")
    print(f"  03_mpnn_submit.py will use these {len(kept)} backbone(s).")


if __name__ == "__main__":
    main()
