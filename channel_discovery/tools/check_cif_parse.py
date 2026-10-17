#!/usr/bin/env python3
"""Validate that the pipeline's mmCIF parser reads YOUR CIF files correctly.

prepare_receptor.py::_mmcif_to_pdb_base reads mmCIF by fixed field position
(resname=4, chain=5, resnum=7, xyz=18/19/20), a layout it documents as
"RFdiffusion/ProteinMPNN output". But mmCIF column order is declared per-file in
its loop_ header, so a different producer can shift those columns. The parse
would not raise — it would silently read the wrong columns as coordinates and
hand fpocket a structure made of nonsense.

This runs the real parser and sanity-checks the result: plausible geometry,
recognisable amino acids, real backbone atom names, and a heme iron sitting
inside the protein rather than off in space.

    python3 check_cif_parse.py <file.cif>
    python3 check_cif_parse.py <dir>/ --sample 5
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fpocket_pipeline"))
from prepare_receptor import (  # noqa: E402
    _mmcif_to_pdb_base, _LEGACY_COLMAP, parse_atom_site_columns,
)

AA = {
    "ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE",
    "LEU", "LYS", "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL",
}
BACKBONE = {"N", "CA", "C", "O"}
HEME = {"HEM", "HEC", "HEB"}


def check(path):
    """Return (ok, [messages]) for one CIF file."""
    msgs = []
    coords, resnames, atomnames, fe = [], [], [], []
    n_lines = serial = 0

    colmap = parse_atom_site_columns(path)
    if colmap:
        msgs.append("read _atom_site header: "
                    + ", ".join(f"{k}={colmap[k]}" for k in ("resname", "x", "y", "z")))
    else:
        msgs.append("no _atom_site header — using legacy positional layout "
                    f"(x={_LEGACY_COLMAP['x']}, y={_LEGACY_COLMAP['y']}, "
                    f"z={_LEGACY_COLMAP['z']})")

    with open(path, errors="replace") as fh:
        for line in fh:
            if not line.startswith(("ATOM", "HETATM")):
                continue
            n_lines += 1
            fields = line.split()
            serial += 1
            base, element = _mmcif_to_pdb_base(fields, serial, colmap)
            if base is None:
                continue
            # Read back from the reconstructed PDB line, exactly as the rest of
            # the pipeline will (read_coords uses these same columns).
            try:
                x, y, z = float(base[30:38]), float(base[38:46]), float(base[46:54])
            except ValueError:
                continue
            coords.append((x, y, z))
            resnames.append(base[17:20].strip().upper())
            aname = base[12:16].strip().upper()
            atomnames.append(aname)
            if aname == "FE" or (element or "").upper() == "FE":
                fe.append((x, y, z))

    if n_lines == 0:
        return False, ["no ATOM/HETATM records found"]
    if not coords:
        return False, [f"{n_lines} atom lines, but the parser produced 0 usable "
                       f"coordinates — field layout almost certainly differs"]

    parsed_frac = len(coords) / n_lines
    msgs.append(f"parsed {len(coords)}/{n_lines} atoms ({parsed_frac:.0%})")
    ok = parsed_frac > 0.9
    if not ok:
        msgs.append("FAIL: most atom lines failed to parse")

    # Geometry: a real protein spans tens of angstroms, centred near its atoms.
    xs = [c[0] for c in coords]; ys = [c[1] for c in coords]; zs = [c[2] for c in coords]
    span = (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
    msgs.append(f"bounding box {span[0]:.1f} x {span[1]:.1f} x {span[2]:.1f} A")
    if max(span) > 500 or max(span) < 5:
        ok = False
        msgs.append("FAIL: implausible extent — likely reading the wrong columns as xyz")
    # A degenerate axis is the signature of an off-by-one column read, where a
    # constant column (model number, occupancy) is taken as a coordinate. The
    # other two axes still look protein-sized, so max(span) alone misses it.
    if min(span) < 5 <= max(span):
        ok = False
        msgs.append(f"FAIL: structure is flat ({min(span):.2f} A on one axis) — a "
                    f"constant column is being read as a coordinate")

    # Residue names: overwhelmingly standard amino acids for a designed protein.
    aa_frac = sum(r in AA for r in resnames) / len(resnames)
    msgs.append(f"standard amino acids: {aa_frac:.0%}")
    if aa_frac < 0.8:
        ok = False
        uniq = sorted(set(resnames))[:12]
        msgs.append(f"FAIL: resname column looks wrong — saw {uniq}")

    # Backbone atom names must be present.
    bb_frac = sum(a in BACKBONE for a in atomnames) / len(atomnames)
    msgs.append(f"backbone atoms (N/CA/C/O): {bb_frac:.0%}")
    if bb_frac < 0.3:
        ok = False
        uniq = sorted(set(atomnames))[:12]
        msgs.append(f"FAIL: atom_name column looks wrong — saw {uniq}")

    # Heme, and an Fe that actually sits inside the protein.
    n_heme = sum(r in HEME for r in resnames)
    if n_heme:
        msgs.append(f"heme residue atoms: {n_heme}")
    else:
        msgs.append("WARN: no HEM/HEC/HEB residue name")
    if fe:
        fx, fy, fz = fe[0]
        inside = (min(xs) <= fx <= max(xs) and min(ys) <= fy <= max(ys)
                  and min(zs) <= fz <= max(zs))
        msgs.append(f"Fe at ({fx:.1f}, {fy:.1f}, {fz:.1f}) — "
                    f"{'inside' if inside else 'OUTSIDE'} the protein box")
        if not inside:
            ok = False
            msgs.append("FAIL: iron is outside the structure — parse is wrong")
    else:
        ok = False
        msgs.append("FAIL: no Fe atom recovered by the parser")

    return ok, msgs


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("target", type=Path, help="a .cif file or a directory of them")
    p.add_argument("--sample", type=int, default=3,
                   help="how many files to check when given a directory")
    args = p.parse_args()

    if args.target.is_file() and args.target.suffix.lower() != ".cif":
        sys.exit(f"{args.target.name} is not a .cif — this checks the mmCIF parser "
                 f"only. Column-format PDB files take a different code path and "
                 f"do not need this check.")

    files = ([args.target] if args.target.is_file()
             else sorted(args.target.glob("*.cif"))[:args.sample])
    if not files:
        sys.exit(f"No .cif files found at {args.target}")

    all_ok = True
    for f in files:
        ok, msgs = check(f)
        print(f"\n{'PASS' if ok else 'FAIL'}  {f.name}")
        for m in msgs:
            print(f"    {m}")
        all_ok &= ok

    print()
    if all_ok:
        print("Parser reads these files correctly — safe to run the pipeline.")
    else:
        print("Parser does NOT read these files correctly. Do not run the pipeline:\n"
              "coordinates would be silently wrong. Paste `head -40` of one file\n"
              "and the parser can be made header-aware instead of positional.")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
