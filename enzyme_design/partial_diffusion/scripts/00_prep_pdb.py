#!/usr/bin/env python3
"""
00_prep_pdb.py — optional PDB preparation utility.

Two modes:

  --trim    Keep only the fixed residues + ligands from the full structure.
            Useful for inspecting exactly what you're anchoring, or for
            generating a de novo theozyme PDB from a full structure.

  --check   Print a summary of what's in the PDB and what partial diffusion
            will fix vs. remodel. No files are written.

Run from the partial_diffusion/ folder:
  python scripts/00_prep_pdb.py --check
  python scripts/00_prep_pdb.py --trim --out inputs/6EKZ_theozyme.pdb
"""
import sys
import math
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import partial_diffusion.config as C


def parse_pdb(path):
    atoms = []
    with open(path) as f:
        for line in f:
            rec = line[:6].strip()
            if rec not in ("ATOM", "HETATM"):
                continue
            atoms.append({
                "line":   line.rstrip("\n"),
                "record": rec,
                "name":   line[12:16].strip(),
                "resn":   line[17:20].strip(),
                "chain":  line[21].strip(),
                "resi":   line[22:26].strip(),
                "x": float(line[30:38]),
                "y": float(line[38:46]),
                "z": float(line[46:54]),
            })
    return atoms


def chain_resi(atom):
    return f"{atom['chain']}{atom['resi']}"


def mode_check(atoms):
    protein = [a for a in atoms if a["record"] == "ATOM"]
    hetatms = [a for a in atoms if a["record"] == "HETATM"]

    residues = sorted({chain_resi(a) for a in protein})
    het_residues = sorted({(a["resn"], chain_resi(a)) for a in hetatms})

    print(f"\nPDB: {C.INPUT_PDB}")
    print(f"  Protein residues : {len(residues)}  ({residues[0]}–{residues[-1]})")
    print(f"  HETATM residues  : {', '.join(f'{r} ({c})' for r, c in het_residues) or 'none'}")

    print(f"\nPartial diffusion will:")
    print(f"  HOLD FIXED (CATRES — sequence identity kept, not redesigned) :")
    for res in C.CATRES:
        atom_note = f"  + pinned atoms: {C.FIXED_ATOMS[res]}" if res in C.FIXED_ATOMS else ""
        in_pdb = any(chain_resi(a) == res for a in protein)
        found = "" if in_pdb else "  ← NOT FOUND in PDB"
        print(f"    {res}{atom_note}{found}")
    print(f"  HOLD FIXED (ligands, both positions and atoms) :")
    for lig in C.LIGAND_NAMES:
        match = [(a["resn"], chain_resi(a)) for a in hetatms if a["resn"] == lig]
        if match:
            print(f"    {lig} at {match[0][1]}")
        else:
            print(f"    {lig}  ← NOT FOUND in PDB — check HEME_NAME / SUBSTRATE_NAME")
    print(f"  REMODEL (all other residues, PARTIAL_T={C.PARTIAL_T} noise steps) :")
    fixed_res = set(C.CATRES)
    free = [r for r in residues if r not in fixed_res]
    print(f"    {len(free)} residues")

    # Find proximal ligand to heme iron
    fe_atoms = [a for a in hetatms if a["name"] in ("FE", "FE1", "FE2") and a["resn"] in C.LIGAND_NAMES]
    if fe_atoms:
        fe = fe_atoms[0]
        print(f"\nHeme iron at ({fe['x']:.2f}, {fe['y']:.2f}, {fe['z']:.2f})")
        close = []
        for a in protein:
            d = math.dist((a["x"], a["y"], a["z"]), (fe["x"], fe["y"], fe["z"]))
            if d < 3.5:
                close.append((d, a["resn"], chain_resi(a), a["name"]))
        if close:
            print("  Protein atoms within 3.5Å of iron (proximal coordination):")
            for d, resn, cr, name in sorted(close):
                flag = " ← in CATRES" if cr in C.CATRES else " ← NOT in CATRES — consider adding"
                print(f"    {d:.2f}Å  {resn} {cr}  {name}{flag}")
        else:
            print("  No protein atoms within 3.5Å of iron")
    print()


def mode_trim(out_path):
    atoms = parse_pdb(C.INPUT_PDB)
    keep_res = set(C.CATRES)
    keep_het = set(C.LIGAND_NAMES)

    kept = []
    for a in atoms:
        if a["record"] == "HETATM" and a["resn"] in keep_het:
            kept.append(a["line"])
        elif a["record"] == "ATOM" and chain_resi(a) in keep_res:
            kept.append(a["line"])

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        f.write("\n".join(kept) + "\nEND\n")

    kept_res = sorted({chain_resi_from_line(l) for l in kept if l[:4] == "ATOM"})
    kept_het = sorted({l[17:20].strip() for l in kept if l[:6].strip() == "HETATM"})
    print(f"Trimmed PDB -> {out_path}")
    print(f"  Kept protein residues : {kept_res}")
    print(f"  Kept HETATM residues  : {kept_het}")
    print("\nNote: this trimmed PDB is for inspection or de novo design.")
    print("Partial diffusion uses the FULL structure (INPUT_PDB in config.py).")


def chain_resi_from_line(line):
    return f"{line[21]}{line[22:26].strip()}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true",
                       help="Print a summary of what will be fixed vs remodelled")
    group.add_argument("--trim",  action="store_true",
                       help="Write a trimmed PDB with only fixed residues + ligands")
    parser.add_argument("--out", default="inputs/trimmed_theozyme.pdb",
                        help="Output path for --trim (default: inputs/trimmed_theozyme.pdb)")
    args = parser.parse_args()

    atoms = parse_pdb(C.INPUT_PDB)

    if args.check:
        mode_check(atoms)
    elif args.trim:
        mode_trim(args.out)
