#!/usr/bin/env python3
"""
08_probe_channel.py — measure the channel in ONE structure and say what to change.

The point of this script is to fail fast. The full pipeline is
RFD3 -> LigandMPNN -> RF3 -> score, and you do need all three to produce a real
design. But if RFD3 has already squeezed the channel shut, no amount of sequence
design will reopen it — so there is no reason to spend GPU on MPNN and RF3 to
find that out. Point this at a single RFD3 backbone, get a verdict in minutes,
change the config, try again.

  fast gate   RFD3 output (.cif.gz)  — necessary condition, minutes.
              Sidechains are present (RFD3 co-diffuses them) but their identities
              are not a designed sequence yet, so treat this as provisional.
  real answer RF3 output / best_designs — after MPNN has actually chosen residues.
              This is the number that counts. Use 07_caver_rescore.py for a whole
              folder of them.

Every probe appends to a log CSV, so you can see which config changes actually
moved the bottleneck rather than guessing.

Usage
-----
    # after a 1-backbone RFD3 run
    python partial_diffusion/scripts/08_probe_channel.py \\
        <WORK>/diffusion_out/partial_rfd3_0.cif.gz \\
        --baseline inputs/PabUPO-II_withHEMEFE_and_NNBT_baseline.json

    # several at once
    python partial_diffusion/scripts/08_probe_channel.py <WORK>/diffusion_out/*.cif.gz \\
        --baseline inputs/..._baseline.json

    # see the history of what you have tried
    python partial_diffusion/scripts/08_probe_channel.py --history
"""
import argparse
import csv
import datetime
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

LOG_FIELDS = ["when", "structure", "experiment", "partial_t", "placeholder",
              "n_flexible", "mpnn_temp", "parent_radius", "bottleneck_radius",
              "delta", "pct", "verdict"]


def parse_args():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("structures", nargs="*", help="Structure(s): .cif.gz, .cif or .pdb")
    p.add_argument("--baseline", default=None,
                   help="Parent baseline JSON from 00_caver_channel.py")
    p.add_argument("--parent", default=None, help="Parent PDB, measured inline instead")
    p.add_argument("--work-dir", default=None, help="Scratch dir for CAVER runs")
    p.add_argument("--log", default=None,
                   help="Iteration log CSV (default: <WORK>/scores/probe_log.csv)")
    p.add_argument("--history", action="store_true", help="Print the log and exit")
    p.add_argument("--keep-substrate", action="store_true",
                   help="Measure holo. Default strips the substrate — see "
                        "07_caver_rescore.py for why this must stay consistent.")
    p.add_argument("--max-length", type=float, default=25.0)
    p.add_argument("--max-curvature", type=float, default=1.5)
    p.add_argument("--probe-radius", type=float, default=None)
    p.add_argument("--noise", type=float, default=0.02,
                   help="Treat |delta| below this as no change (A, default 0.02). "
                        "Staging every structure under one filename removes the "
                        "large filename-dependent variance, but leave a small "
                        "floor rather than trusting the third decimal.")
    return p.parse_args()


def load_config():
    try:
        return importlib.import_module(
            importlib.import_module("partial_diffusion").default_config())
    except Exception:
        return None


def to_pdb(struct, dest_dir):
    """Normalise .cif.gz / .cif / .pdb to a plain PDB path."""
    struct = Path(struct)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    name = struct.name
    if name.endswith(".cif.gz"):
        cif = dest_dir / name[:-3]
        with gzip.open(struct, "rb") as gz, open(cif, "wb") as out:
            shutil.copyfileobj(gz, out)
        struct = cif
    if struct.suffix == ".pdb":
        return struct

    dest = dest_dir / f"{struct.stem}.pdb"
    sys.path.insert(0, str(CIF_TO_PDB.parent))
    import cif_to_pdb
    return dest if cif_to_pdb.convert(struct, dest) else None


def verdict_for(delta, noise):
    if delta > noise:
        return "WIDER"
    if delta < -noise:
        return "NARROWER"
    return "UNCHANGED"


def advise(verdict, C):
    """Concrete next moves, based on what the config currently says."""
    placeholder = bool(getattr(C, "CHANNEL_PLACEHOLDER", "")) if C else False
    partial_t = getattr(C, "PARTIAL_T", None) if C else None
    temp = getattr(C, "MPNN_TEMPERATURE", 0.1) if C else None
    tips = []

    if verdict == "WIDER":
        tips.append("Backbone opened. Promote to a full run (RFD3 -> MPNN -> RF3),")
        tips.append("then confirm with 07_caver_rescore.py — MPNN picks the real")
        tips.append("residues, so the final channel can differ from this one.")
        if temp is not None and temp <= 0.1:
            tips.append(f"Raise MPNN_TEMPERATURE ({temp} is near-argmax) so the")
            tips.append("sequences are not near-duplicates.")
        return tips

    if not placeholder:
        tips.append("CHANNEL_PLACEHOLDER is OFF — this is the first thing to change.")
        tips.append("Nothing currently rewards keeping the channel open, so RFD3")
        tips.append("packs into it. Generate one with 00_caver_channel.py and set")
        tips.append("CHANNEL_PLACEHOLDER in the config.")
    else:
        tips.append("Placeholder is on but the channel did not open. Try")
        tips.append("--placeholder-shrink 0.8 in 00_caver_channel.py so the dummy")
        tips.append("atoms mark only the already-wide stretch, pushing RFD3 to")
        tips.append("open the narrow part instead of freezing the current shape.")

    if partial_t is not None and partial_t < 8:
        tips.append(f"PARTIAL_T is {partial_t}; try 10-12 for more backbone freedom.")

    tips.append("Check FLEXIBLE_RESIDUES actually line THIS tunnel — re-derive with")
    tips.append("00_caver_channel.py. Residues spread over several different")
    tips.append("tunnels dilute the change instead of opening one channel.")
    return tips


def default_dirs(structures, C):
    """Where to put CAVER scratch and the iteration log.

    Derived from the structures being probed, NOT from the ambient config: the
    config that happens to be importable is often a different person's, or a
    different experiment, and writing there either fails on permissions or
    scatters results into someone else's run. A pilot's backbones live in
    <run>/diffusion_out/, so <run> is the natural home for its scratch, and the
    directory holding all the runs is where a cross-run log belongs.
    """
    if structures:
        first = Path(structures[0]).resolve()
        run_dir = first.parent.parent          # <run>/diffusion_out/x.cif.gz -> <run>
        return run_dir / "probe", run_dir.parent / "probe_log.csv"
    if C is not None:
        return Path(C.SCORES_DIR) / "probe", Path(C.SCORES_DIR) / "probe_log.csv"
    return Path("probe_work"), Path("probe_log.csv")


def main():
    args = parse_args()
    C = load_config()

    default_work, default_log = default_dirs(args.structures, C)
    log_path = Path(args.log) if args.log else default_log

    if args.history:
        if not log_path.exists():
            sys.exit(f"No probe log yet at {log_path}")
        rows = list(csv.DictReader(open(log_path)))
        if not rows:
            sys.exit("Probe log is empty.")
        print(f"{'when':17s} {'partial_t':>9s} {'plc':>4s} {'flex':>5s} "
              f"{'radius':>7s} {'delta':>7s}  verdict")
        for r in rows:
            print(f"{r['when'][:16]:17s} {r['partial_t']:>9s} "
                  f"{('yes' if r['placeholder'] == 'True' else 'no'):>4s} "
                  f"{r['n_flexible']:>5s} {r['bottleneck_radius']:>7s} "
                  f"{r['delta']:>7s}  {r['verdict']}")
        return

    if not args.structures:
        sys.exit("Give at least one structure, or --history.")
    if not cu.caver_available():
        sys.exit(f"CAVER not runnable — need java and {cu.CAVER_JAR}")

    work = Path(args.work_dir) if args.work_dir else default_work
    try:
        work.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        sys.exit(f"Cannot write CAVER scratch to {work}\n"
                 f"Pass --work-dir <a directory you own>, e.g.\n"
                 f"  --work-dir $HOME/probe_work")
    strip = None if args.keep_substrate else "auto"
    mode = "holo" if args.keep_substrate else "apo"

    # ── parent baseline ──────────────────────────────────────────────────────
    if args.baseline:
        base = json.loads(Path(args.baseline).read_text())
        parent_r = base["bottleneck_radius"]
        base_mode = base.get("measured")
        if base_mode and base_mode != mode:
            sys.exit(f"Baseline measured {base_mode}, probing {mode} — not comparable. "
                     f"Rebuild the baseline or flip --keep-substrate.")
    else:
        parent = args.parent or (C.INPUT_PDB if C else None)
        if not parent:
            sys.exit("Pass --baseline or --parent.")
        t = cu.best_tunnel(cu.run_caver(parent, work / "_parent", strip=strip,
                                        probe_radius=args.probe_radius),
                           max_length=args.max_length, max_curvature=args.max_curvature)
        if t is None:
            sys.exit("Could not measure the parent channel.")
        parent_r = t["bottleneck_radius"]

    print(f"Parent bottleneck : {parent_r:.3f} A  (measured {mode})\n")

    results = []
    for s in args.structures:
        s = Path(s)
        if not s.exists():
            print(f"  {s.name}: not found")
            continue
        pdb = to_pdb(s, work / "pdb")
        if pdb is None:
            print(f"  {s.name}: could not convert to PDB")
            continue

        out = cu.run_caver(pdb, work / s.name.split(".")[0], strip=strip,
                           probe_radius=args.probe_radius)
        t = cu.best_tunnel(out, max_length=args.max_length,
                           max_curvature=args.max_curvature)
        if t is None:
            fe, _, _ = cu.find_heme_fe(pdb)
            print(f"  {s.name}: {'no heme — RFD3 may have lost the cofactor' if fe is None else 'no tunnel found'}")
            continue

        r = t["bottleneck_radius"]
        delta = r - parent_r
        v = verdict_for(delta, args.noise)
        results.append((s.name, r, delta, v))
        print(f"  {s.name:<42s} {r:.3f} A   {delta:+.3f} "
              f"({100*delta/parent_r:+.1f}%)   {v}")

    if not results:
        sys.exit("\nNothing measured.")

    best = max(results, key=lambda x: x[2])
    verdict = best[3]

    # ── append to the iteration log ──────────────────────────────────────────
    row = {
        "when": datetime.datetime.now().isoformat(timespec="seconds"),
        "structure": best[0],
        "experiment": getattr(C, "EXPERIMENT", "") if C else "",
        "partial_t": getattr(C, "PARTIAL_T", "") if C else "",
        "placeholder": bool(getattr(C, "CHANNEL_PLACEHOLDER", "")) if C else "",
        "n_flexible": len(getattr(C, "FLEXIBLE_RESIDUES", [])) if C else "",
        "mpnn_temp": getattr(C, "MPNN_TEMPERATURE", "") if C else "",
        "parent_radius": round(parent_r, 4),
        "bottleneck_radius": round(best[1], 4),
        "delta": round(best[2], 4),
        "pct": round(100 * best[2] / parent_r, 1),
        "verdict": verdict,
    }
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        new = not log_path.exists()
        with open(log_path, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=LOG_FIELDS, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerow(row)
        logged = True
    except (PermissionError, OSError) as e:
        # Never lose a finished measurement to a logging problem — the CAVER
        # runs are the expensive part and they are already done.
        print(f"\n  (could not write log to {log_path}: {e.__class__.__name__} "
              f"— pass --log <path you own> to keep the history)")
        logged = False

    print(f"\n--- BEST OF {len(results)}: {best[0]}  {best[2]:+.3f} A  {verdict} ---")
    for line in advise(verdict, C):
        print(f"  {line}")
    if logged:
        print(f"\n  logged -> {log_path}   (see the trend with --history)")


if __name__ == "__main__":
    main()
