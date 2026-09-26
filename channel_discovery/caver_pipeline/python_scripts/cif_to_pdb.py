#!/usr/bin/env python3
"""Convert mmCIF (RFdiffusion/ProteinMPNN space-separated format) to plain PDB.

run_batch.py only globs *.pdb, and CAVER's own heme/element handling expects
real PDB files (real element symbols in columns 77-78), not the AutoDock-typed
PDBQTs from fpocket_pipeline. This reuses the exact mmCIF field parsing from
fpocket_pipeline/prepare_receptor.py (already tuned for these files) but emits
standard PDB ATOM/HETATM lines instead of PDBQT.

Examples
--------
    python3 cif_to_pdb.py ../input_files/design.cif
    python3 cif_to_pdb.py ../input_files/          # batch: every .cif in the dir
"""
import argparse
import sys
from pathlib import Path

FPOCKET_DIR = Path(__file__).resolve().parents[2] / "fpocket_pipeline"
sys.path.insert(0, str(FPOCKET_DIR))
from prepare_receptor import (  # noqa: E402
    _mmcif_to_pdb_base, _WATER_RESNAMES, _LEGACY_COLMAP, parse_atom_site_columns,
)


def convert(input_file: Path, output_pdb: Path, remove_water: bool = True) -> bool:
    lines_out = []
    skipped_water = skipped_altloc = skipped_bad = 0
    serial = 0

    # Column order comes from this file's own _atom_site header — it is not
    # fixed across mmCIF producers.
    colmap = parse_atom_site_columns(input_file)
    cm = colmap or _LEGACY_COLMAP

    with open(input_file) as fh:
        for line in fh:
            if not line.startswith(("ATOM", "HETATM")):
                continue

            fields = line.split()
            if colmap is None and len(fields) <= 15:
                skipped_bad += 1
                continue

            i_alt = cm.get("alt_loc")
            altloc = (fields[i_alt] if i_alt is not None and len(fields) > i_alt
                      else ".")
            if altloc not in (".", " ", "A"):
                skipped_altloc += 1
                continue

            i_res = cm.get("resname")
            resname = (fields[i_res].upper()
                       if i_res is not None and len(fields) > i_res else "")
            if remove_water and resname in _WATER_RESNAMES:
                skipped_water += 1
                continue

            serial += 1
            base, element = _mmcif_to_pdb_base(fields, serial, colmap)
            if base is None:
                skipped_bad += 1
                continue

            lines_out.append(f"{base}          {element:>2s}  \n")

    if not lines_out:
        print(f"Warning: no ATOM/HETATM records written for {input_file.name}",
              file=sys.stderr)
        return False

    lines_out.append("END\n")
    output_pdb.write_text("".join(lines_out))

    notes = []
    if skipped_water:
        notes.append(f"{skipped_water} water(s) removed")
    if skipped_altloc:
        notes.append(f"{skipped_altloc} alt-conformation atom(s) removed")
    if skipped_bad:
        notes.append(f"{skipped_bad} unparseable line(s) skipped")
    note_str = f"  ({', '.join(notes)})" if notes else ""
    print(f"  {input_file.name} -> {output_pdb.name}{note_str}")
    return True


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("input", type=Path,
                    help="mmCIF file or directory of .cif files")
    p.add_argument("-o", "--output", type=Path, default=None,
                    help="Output PDB file or directory (default: same location as input)")
    p.add_argument("--keep-water", action="store_true",
                    help="Do not remove crystallographic water molecules")
    p.add_argument("--overwrite", action="store_true",
                    help="Re-convert even if the .pdb already exists")
    args = p.parse_args()
    remove_water = not args.keep_water

    if args.input.is_dir():
        files = sorted(args.input.glob("*.cif"))
        if not files:
            sys.exit(f"No .cif files found in {args.input}")
        out_dir = args.output if args.output else args.input
        out_dir.mkdir(parents=True, exist_ok=True)
        ok = failed = skipped = 0
        for f in files:
            out = out_dir / f.with_suffix(".pdb").name
            if out.exists() and not args.overwrite:
                print(f"  [SKIP] {f.name}  (.pdb already exists; use --overwrite to redo)")
                skipped += 1
                continue
            if convert(f, out, remove_water=remove_water):
                ok += 1
            else:
                failed += 1
        print(f"\n{ok} converted, {skipped} skipped, {failed} failed.")

    elif args.input.is_file():
        out = args.output if args.output else args.input.with_suffix(".pdb")
        if out.exists() and not args.overwrite:
            sys.exit(f"[SKIP] {out} already exists (use --overwrite to redo)")
        if not convert(args.input, out, remove_water=remove_water):
            sys.exit(1)

    else:
        sys.exit(f"Input not found: {args.input}")


if __name__ == "__main__":
    main()
