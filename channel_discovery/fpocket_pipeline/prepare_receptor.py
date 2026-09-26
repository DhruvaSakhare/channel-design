#!/usr/bin/env python3
"""Prepare receptor PDB or mmCIF file(s) for AutoDock Vina.

Converts ATOM and HETATM records to PDBQT format: maps elements to AutoDock
atom types and writes zero partial charges (sufficient for Vina's built-in
scoring function, which does not use receptor partial charges).

Handles two input formats automatically:
  - Standard PDB column format (coordinates at columns 31-54)
  - mmCIF space-separated format as produced by RFdiffusion/ProteinMPNN
    (coordinates at space-separated fields 18-20)

Designed for heme-containing enzymes (UPOs, P450s): the heme cofactor and its
iron are preserved and correctly typed (Fe), while crystallographic waters are
removed by default.

Limitations
-----------
- Hydrogens already present are passed through; missing hydrogens are NOT added.
  For best results, run through a protonation tool (reduce, openbabel --addh)
  before using this script.
- Partial charges are set to 0.000. Vina's scoring function does not require
  receptor charges, so this is fine for screening purposes.

Examples
--------
    # Single PDB or CIF file
    python3 prepare_receptor.py -i inputs/8AV5_heme.pdb
    python3 prepare_receptor.py -i inputs/design.cif

    # Batch: all .pdb and .cif files in a directory
    python3 prepare_receptor.py -i inputs/

    # Keep crystallographic waters
    python3 prepare_receptor.py -i inputs/ --keep-water
"""
import argparse
import sys
from pathlib import Path

_ELEMENT_TO_ADTYPE = {
    "C":  "C",
    "N":  "N",
    "O":  "OA",
    "S":  "SA",
    "H":  "HD",
    "P":  "P",
    "F":  "F",
    "CL": "Cl",
    "BR": "Br",
    "I":  "I",
    "FE": "Fe",
    "MG": "Mg",
    "CA": "Ca",
    "MN": "Mn",
    "ZN": "Zn",
    "CU": "Cu",
    "NA": "Na",
    "K":  "K",
}

_WATER_RESNAMES = {"HOH", "WAT", "H2O", "DOD"}

# mmCIF _atom_site columns are declared per file in its loop_ header, so their
# positions are NOT fixed across producers. We read that header and map columns
# by name; _LEGACY_COLMAP is the fallback for minimal CIFs that have no header
# (the original RFdiffusion/ProteinMPNN layout this module was written against).
_LEGACY_COLMAP = {
    "record": 0, "element": 1, "atom_name": 2, "alt_loc": 3,
    "resname": 4, "chain": 5, "resnum": 7, "x": 18, "y": 19, "z": 20,
}

# auth_* is preferred over label_* for residue number and chain: mmCIF writes
# label_seq_id as '.' for HETATM groups, which would make int() fail and drop
# every heme atom — exactly the cofactor this pipeline is anchored on.
_ATOM_SITE_ALIASES = {
    "record":    ["group_PDB"],
    "element":   ["type_symbol"],
    "atom_name": ["label_atom_id", "auth_atom_id"],
    "alt_loc":   ["label_alt_id"],
    "resname":   ["auth_comp_id", "label_comp_id"],
    "chain":     ["auth_asym_id", "label_asym_id"],
    "resnum":    ["auth_seq_id", "label_seq_id"],
    "x":         ["Cartn_x"],
    "y":         ["Cartn_y"],
    "z":         ["Cartn_z"],
}

_REQUIRED_COLS = ("record", "element", "atom_name", "resname",
                  "chain", "resnum", "x", "y", "z")


def parse_atom_site_columns(path):
    """Return {field_name: index} from a file's _atom_site loop_ header.

    Returns None when the file has no such header (minimal CIFs), in which case
    callers should fall back to _LEGACY_COLMAP.
    """
    names = []
    try:
        with open(path, errors="replace") as fh:
            for line in fh:
                s = line.strip()
                if s.startswith("_atom_site."):
                    names.append(s.split(".", 1)[1].split()[0])
                elif names:
                    break          # header block has ended
    except OSError:
        return None

    if not names:
        return None

    index = {n: i for i, n in enumerate(names)}
    colmap = {}
    for key, aliases in _ATOM_SITE_ALIASES.items():
        for alias in aliases:
            if alias in index:
                colmap[key] = index[alias]
                break

    missing = [k for k in _REQUIRED_COLS if k not in colmap]
    if missing:
        print(f"Warning: {Path(path).name} _atom_site header is missing "
              f"{', '.join(missing)} — falling back to positional parsing",
              file=sys.stderr)
        return None
    return colmap


def _guess_element(atom_name: str) -> str:
    """Derive element from atom name when PDB element column is absent."""
    name = atom_name.strip().lstrip("0123456789 ")
    alpha = "".join(c for c in name if c.isalpha()).upper()
    if len(alpha) >= 2 and alpha[:2] in _ELEMENT_TO_ADTYPE:
        return alpha[:2]
    return alpha[:1] if alpha else "C"


def _mmcif_to_pdb_base(fields: list, serial: int, colmap: dict = None):
    """Reconstruct a 66-char PDB-format base line from mmCIF space-separated fields.

    colmap maps field names to column indices, as returned by
    parse_atom_site_columns(). When omitted, _LEGACY_COLMAP is used — the
    positional RFdiffusion/ProteinMPNN layout. Passing the file's real column
    map is strongly preferred: producers that emit a full _atom_site header put
    the coordinates elsewhere, and the legacy offsets can read neighbouring
    numeric columns as x/y/z without raising.

    Returns (base_str, element_str) or (None, None) on parse failure.
    """
    c = colmap or _LEGACY_COLMAP
    try:
        record    = fields[c["record"]]
        element   = fields[c["element"]].upper()
        atom_name = fields[c["atom_name"]]
        resname   = fields[c["resname"]][:3]
        chain     = fields[c["chain"]][:1]
        resnum    = int(fields[c["resnum"]])
        x         = float(fields[c["x"]])
        y         = float(fields[c["y"]])
        z         = float(fields[c["z"]])
    except (IndexError, ValueError, KeyError):
        return None, None

    # PDB atom name: 1-char elements get a leading space (e.g., " CA ")
    aname = f" {atom_name:<3s}" if len(atom_name) < 4 else f"{atom_name:<4s}"

    base = (
        f"{record:<6s}{serial:5d} {aname} {resname:<3s} {chain}"
        f"{resnum:4d}    {x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.10"
    )
    return base[:66].ljust(66), element


def convert(input_file: Path, output_pdbqt: Path, remove_water: bool = True) -> bool:
    """Convert one PDB or mmCIF file to PDBQT.

    Returns True on success, False on failure.
    """
    lines_out = []
    skipped_water = 0
    skipped_altloc = 0
    serial = 0

    # Read this file's own _atom_site column order; None for column-format PDB
    # or for minimal CIFs without a header (then _LEGACY_COLMAP applies).
    colmap = parse_atom_site_columns(input_file)
    cm = colmap or _LEGACY_COLMAP

    try:
        with open(input_file) as fh:
            for line in fh:
                if not line.startswith(("ATOM", "HETATM")):
                    continue

                fields = line.split()
                is_mmcif = colmap is not None or len(fields) > 15

                if is_mmcif:
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
                        continue
                else:
                    # Standard PDB column format
                    altloc = line[16] if len(line) > 16 else " "
                    if altloc not in (" ", "A"):
                        skipped_altloc += 1
                        continue
                    resname = line[17:20].strip().upper()
                    if remove_water and resname in _WATER_RESNAMES:
                        skipped_water += 1
                        continue
                    element = line[76:78].strip().upper() if len(line) > 76 else ""
                    if not element:
                        element = _guess_element(line[12:16])
                    serial += 1
                    base = line[:66].rstrip().ljust(66)

                ad_type = _ELEMENT_TO_ADTYPE.get(element, element.capitalize() or "C")
                lines_out.append(f"{base}    {0.000:6.3f} {ad_type:<2s}\n")

    except OSError as e:
        print(f"Error reading {input_file}: {e}", file=sys.stderr)
        return False

    if not lines_out:
        print(f"Warning: no ATOM/HETATM records written for {input_file.name}",
              file=sys.stderr)
        return False

    try:
        output_pdbqt.write_text("".join(lines_out))
    except OSError as e:
        print(f"Error writing {output_pdbqt}: {e}", file=sys.stderr)
        return False

    notes = []
    if skipped_water:
        notes.append(f"{skipped_water} water(s) removed")
    if skipped_altloc:
        notes.append(f"{skipped_altloc} alt-conformation atom(s) removed")
    note_str = f"  ({', '.join(notes)})" if notes else ""
    print(f"  {input_file.name} -> {output_pdbqt.name}{note_str}")
    return True


def prepare_directory(input_dir: Path, output_dir: Path,
                      remove_water: bool = True, overwrite: bool = False):
    """Batch-convert all .pdb and .cif files in input_dir."""
    files = sorted(input_dir.glob("*.pdb")) + sorted(input_dir.glob("*.cif"))
    if not files:
        print(f"No .pdb or .cif files found in {input_dir}", file=sys.stderr)
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    ok = failed = skipped = 0

    for f in files:
        out = output_dir / f.with_suffix(".pdbqt").name
        if out.exists() and not overwrite:
            print(f"  [SKIP] {f.name}  (PDBQT already exists; use --overwrite to redo)")
            skipped += 1
            continue
        if convert(f, out, remove_water=remove_water):
            ok += 1
        else:
            failed += 1

    print(f"\n{ok} converted, {skipped} skipped, {failed} failed.")


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("-i", "--input", type=Path, required=True,
                   help="PDB/CIF file or directory of PDB/CIF files")
    p.add_argument("-o", "--output", type=Path, default=None,
                   help="Output PDBQT file or directory. "
                        "Defaults to same location as input with .pdbqt extension.")
    p.add_argument("--keep-water", action="store_true",
                   help="Do not remove crystallographic water molecules")
    p.add_argument("--overwrite", action="store_true",
                   help="Re-convert even if the PDBQT already exists")
    args = p.parse_args()

    remove_water = not args.keep_water

    if args.input.is_dir():
        out_dir = args.output if args.output else args.input
        prepare_directory(args.input, out_dir,
                          remove_water=remove_water, overwrite=args.overwrite)

    elif args.input.is_file():
        out = args.output if args.output else args.input.with_suffix(".pdbqt")
        if out.exists() and not args.overwrite:
            print(f"[SKIP] {out} already exists (use --overwrite to redo)")
            sys.exit(0)
        if not convert(args.input, out, remove_water=remove_water):
            sys.exit(1)

    else:
        sys.exit(f"Input not found: {args.input}")


if __name__ == "__main__":
    main()
