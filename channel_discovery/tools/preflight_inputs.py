#!/usr/bin/env python3
"""Screen a directory of receptor structures BEFORE running the pipeline on them.

The pipeline anchors everything on the heme iron: pipeline.py calls
find_heme_fe() during filtering, and a structure without one is recorded FAIL
("no heme") and then silently skipped by the entire caver stage. Predicted
structures (AlphaFold, ESMFold, plain ProteinMPNN/RFdiffusion output) usually
have no cofactor at all, so a whole batch of them fails without ever erroring.

This reproduces find_heme_fe()'s exact search order in pure Python — no fpocket,
no java, no conda env needed — so 1000 structures screen in seconds. It writes a
manifest of usable structures.

    python3 preflight_inputs.py /path/to/my_structures \\
        -o manifest.txt --report preflight.tsv
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

HEME_RESNAMES = {"HEM", "HEC", "HEB"}


def scan(path):
    """Return (status, detail) mirroring find_heme_fe()'s search order."""
    n_atoms = 0
    has_heme_res = False
    has_heme_fe = False
    has_any_fe = False
    chains = set()

    try:
        with open(path, errors="replace") as fh:
            for line in fh:
                if not line.startswith(("ATOM", "HETATM")):
                    continue
                n_atoms += 1
                # mmCIF-style space-separated rows won't have fixed columns;
                # fall back to whitespace fields for resname/atomname.
                if len(line) > 54 and line[30:38].strip().replace(".", "").replace("-", "").isdigit():
                    resname = line[17:20].strip().upper()
                    atomname = line[12:16].strip().upper()
                    chains.add(line[21:22])
                else:
                    f = line.split()
                    resname = f[4].upper() if len(f) > 4 else ""
                    atomname = f[2].upper() if len(f) > 2 else ""
                if resname in HEME_RESNAMES:
                    has_heme_res = True
                    if atomname == "FE":
                        has_heme_fe = True
                if atomname == "FE":
                    has_any_fe = True
    except OSError as e:
        return "UNREADABLE", str(e)

    if n_atoms == 0:
        return "EMPTY", "no ATOM/HETATM records"
    if has_heme_fe:
        return "OK", "heme Fe"
    if has_heme_res:
        return "OK", "heme centroid (no FE atom)"
    if has_any_fe:
        return "OK", "Fe in HETATM (non-standard resname)"
    return "NO_HEME", f"{n_atoms} atoms, {len(chains)} chain(s), no heme/Fe"


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input_dir", type=Path)
    p.add_argument("-o", "--manifest", type=Path, default=None,
                   help="Write usable structures here, one path per line")
    p.add_argument("--report", type=Path, default=None,
                   help="Write the full per-structure table here (TSV)")
    args = p.parse_args()

    files = sorted(args.input_dir.glob("*.pdb")) + sorted(args.input_dir.glob("*.cif"))
    if not files:
        sys.exit(f"No .pdb or .cif files in {args.input_dir}")

    counts = Counter()
    rows = []
    usable = []
    for f in files:
        status, detail = scan(f)
        counts[status] += 1
        rows.append((f.stem, status, detail))
        if status == "OK":
            usable.append(f)

    print(f"Scanned {len(files)} structure(s) in {args.input_dir}\n")
    for status in ("OK", "NO_HEME", "EMPTY", "UNREADABLE"):
        if counts[status]:
            print(f"  {status:<12} {counts[status]:>5}")

    bad = [r for r in rows if r[1] != "OK"]
    if bad:
        print(f"\nFirst {min(10, len(bad))} problem structure(s):")
        for stem, status, detail in bad[:10]:
            print(f"  {status:<12} {stem:<40} {detail}")

    if args.report:
        with open(args.report, "w") as fh:
            fh.write("stem\tstatus\tdetail\n")
            for stem, status, detail in rows:
                fh.write(f"{stem}\t{status}\t{detail}\n")
        print(f"\nFull report: {args.report}")

    if args.manifest:
        with open(args.manifest, "w") as fh:
            for f in usable:
                fh.write(f"{f.resolve()}\n")
        print(f"Manifest ({len(usable)} usable): {args.manifest}")

    if not usable:
        print("\nNothing usable — every structure would FAIL at the heme check.", file=sys.stderr)
        print("If these are predicted models, the heme cofactor must be added "
              "(co-fold it, or superpose a template heme) before this pipeline "
              "can do anything with them.", file=sys.stderr)
        sys.exit(1)

    if counts["NO_HEME"]:
        pct = 100 * counts["NO_HEME"] / len(files)
        print(f"\nWarning: {counts['NO_HEME']} structure(s) ({pct:.0f}%) have no heme "
              f"and will be dropped.")


if __name__ == "__main__":
    main()
