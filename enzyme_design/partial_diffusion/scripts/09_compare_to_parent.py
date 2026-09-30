#!/usr/bin/env python3
"""
09_compare_to_parent.py — did the design keep the core and change only the channel?

The whole premise of this pipeline is "hold 313 residues rigid + native, let 22
move and be redesigned". That is an ASSUMPTION about what RFD3/MPNN/RF3 actually
did, not a guarantee — RF3 in particular refolds from scratch and is free to move
anything. This checks it.

Superimposes each design onto the parent using ONLY the pinned residues, then
reports the two numbers separately:

  pinned RMSD    should be small (~0.5 A or less). This is the core. If it is
                 large, the design drifted and "we only changed the channel" is
                 not true.
  flexible RMSD  expected to be LARGER — these are the channel residues that were
                 supposed to move. A value near zero here means nothing happened.

Also reports sequence identity at both sets: MPNN was told to keep the pinned
residues native (via --fixed_residues), so pinned identity should be ~100%.
Anything less means residues changed that were supposed to be frozen.

Usage
-----
    python partial_diffusion/scripts/09_compare_to_parent.py <design.cif|.cif.gz|.pdb> [...]
    python partial_diffusion/scripts/09_compare_to_parent.py <WORK>/best_designs/*.cif
    python partial_diffusion/scripts/09_compare_to_parent.py <design> --parent <parent.pdb>
"""
import argparse
import gzip
import importlib
import os
import shutil
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "lib"))
from paths import CIF_TO_PDB  # noqa: E402

THREE_TO_ONE = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C", "GLN": "Q",
    "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I", "LEU": "L", "LYS": "K",
    "MET": "M", "PHE": "F", "PRO": "P", "SER": "S", "THR": "T", "TRP": "W",
    "TYR": "Y", "VAL": "V",
}


def parse_args():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("designs", nargs="+", help="Design structure(s)")
    p.add_argument("--parent", default=None,
                   help="Parent PDB (default: the config's INPUT_PDB)")
    p.add_argument("--chain", default="A", help="Protein chain (default: A)")
    p.add_argument("--flexible", default=None,
                   help="Comma-separated residue numbers, or a *_flex.json. "
                        "Default: the config's FLEXIBLE_RESIDUES.")
    p.add_argument("--work-dir", default=None, help="Scratch for CIF conversion")
    p.add_argument("--per-residue", action="store_true",
                   help="Also print per-residue CA deviation for the flexible set")
    return p.parse_args()


def load_ca(pdb_path, chain="A"):
    """{resnum: (resname, np.array([x,y,z]))} for CA atoms of one chain."""
    out = {}
    with open(pdb_path) as f:
        for line in f:
            if not line.startswith("ATOM"):
                continue
            if line[21] != chain or line[12:16].strip() != "CA":
                continue
            # Skip altloc B+ so a residue can't appear twice.
            if line[16] not in (" ", "A"):
                continue
            try:
                num = int(line[22:26])
            except ValueError:
                continue
            out[num] = (line[17:20].strip(),
                        np.array([float(line[30:38]), float(line[38:46]),
                                  float(line[46:54])]))
    return out


def to_pdb(struct, dest_dir):
    struct = Path(struct)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    if struct.name.endswith(".cif.gz"):
        cif = dest_dir / struct.name[:-3]
        with gzip.open(struct, "rb") as gz, open(cif, "wb") as out:
            shutil.copyfileobj(gz, out)
        struct = cif
    if struct.suffix == ".pdb":
        return struct
    dest = dest_dir / f"{struct.stem}.pdb"
    if dest.exists():
        return dest
    sys.path.insert(0, str(CIF_TO_PDB.parent))
    import cif_to_pdb
    return dest if cif_to_pdb.convert(struct, dest) else None


def kabsch_rmsd(mobile, ref):
    """Superimpose mobile onto ref, return (rmsd, rotation, mobile_centroid,
    ref_centroid). Standard Kabsch: centre both, SVD of the covariance, fix
    reflection via the determinant sign."""
    mc, rc = mobile.mean(axis=0), ref.mean(axis=0)
    m, r = mobile - mc, ref - rc
    u, _, vt = np.linalg.svd(m.T @ r)
    d = np.sign(np.linalg.det(vt.T @ u.T))
    rot = vt.T @ np.diag([1.0, 1.0, d]) @ u.T
    aligned = (rot @ m.T).T
    rmsd = float(np.sqrt(((aligned - r) ** 2).sum(axis=1).mean()))
    return rmsd, rot, mc, rc


def apply_transform(coords, rot, mc, rc):
    return (rot @ (coords - mc).T).T + rc


def main():
    args = parse_args()

    C = None
    try:
        C = importlib.import_module(
            importlib.import_module("partial_diffusion").default_config())
    except Exception:
        pass

    parent_path = args.parent or (C.INPUT_PDB if C else None)
    if not parent_path:
        sys.exit("Pass --parent (no importable config here).")
    parent_path = Path(parent_path)
    if not parent_path.exists():
        sys.exit(f"Parent not found: {parent_path}")

    # flexible set
    if args.flexible:
        src = Path(args.flexible)
        if src.suffix == ".json" and src.exists():
            import json
            flexible = set(json.loads(src.read_text())["flexible_residues"])
        else:
            flexible = {int(x) for x in args.flexible.replace(" ", "").split(",") if x}
    elif C is not None and hasattr(C, "FLEXIBLE_RESIDUES"):
        flexible = set(C.FLEXIBLE_RESIDUES)
    else:
        sys.exit("Pass --flexible (config has no FLEXIBLE_RESIDUES).")

    parent = load_ca(parent_path, args.chain)
    if not parent:
        sys.exit(f"No chain-{args.chain} CA atoms in {parent_path}")

    work = Path(args.work_dir) if args.work_dir else (
        Path(C.SCORES_DIR) / "compare_work" if C else Path("compare_work"))

    print(f"Parent   : {parent_path.name}  ({len(parent)} residues, chain {args.chain})")
    print(f"Flexible : {len(flexible)} residues (allowed to move/redesign)")
    print(f"Pinned   : {len(set(parent) - flexible)} residues (should be unchanged)\n")

    hdr = (f"{'design':<44s} {'pinRMSD':>8s} {'flexRMSD':>9s} "
           f"{'pinID%':>7s} {'flexID%':>8s}  {'n':>4s}")
    print(hdr)
    print("-" * len(hdr))

    for d in args.designs:
        d = Path(d)
        if not d.exists():
            print(f"{d.name:<44s} not found")
            continue
        pdb = to_pdb(d, work)
        if pdb is None:
            print(f"{d.name:<44s} conversion failed")
            continue
        design = load_ca(pdb, args.chain)

        # Compare only residues present in BOTH, so a design with gaps or a
        # different numbering range can't silently shift the alignment.
        common = sorted(set(parent) & set(design))
        pin = [r for r in common if r not in flexible]
        flx = [r for r in common if r in flexible]
        if len(pin) < 3:
            print(f"{d.name:<44s} too few pinned residues in common ({len(pin)})")
            continue

        p_pin = np.array([parent[r][1] for r in pin])
        d_pin = np.array([design[r][1] for r in pin])
        pin_rmsd, rot, mc, rc = kabsch_rmsd(d_pin, p_pin)

        if flx:
            d_flx = apply_transform(np.array([design[r][1] for r in flx]), rot, mc, rc)
            p_flx = np.array([parent[r][1] for r in flx])
            flex_rmsd = float(np.sqrt(((d_flx - p_flx) ** 2).sum(axis=1).mean()))
        else:
            flex_rmsd = float("nan")

        pin_id = 100.0 * sum(parent[r][0] == design[r][0] for r in pin) / len(pin)
        flex_id = (100.0 * sum(parent[r][0] == design[r][0] for r in flx) / len(flx)
                   if flx else float("nan"))

        print(f"{d.name:<44s} {pin_rmsd:8.3f} {flex_rmsd:9.3f} "
              f"{pin_id:7.1f} {flex_id:8.1f}  {len(common):4d}")

        if args.per_residue and flx:
            dev = np.sqrt(((d_flx - p_flx) ** 2).sum(axis=1))
            order = np.argsort(-dev)
            print("      largest CA shifts (flexible set):")
            for i in order[:10]:
                r = flx[i]
                print(f"        {parent[r][0]}{r:<4d} {design[r][0]:>3s}  {dev[i]:6.2f} A")

    print(f"\nHow to read this:")
    print(f"  pinRMSD  core displacement. Small (<~0.5 A) = the fold was held.")
    print(f"           Large = the design drifted; 'only the channel changed' is false.")
    print(f"  flexRMSD channel residues. Should EXCEED pinRMSD — that is the")
    print(f"           intended change. Near zero means nothing actually moved.")
    print(f"  pinID%   should be ~100: MPNN was told to keep these native.")
    print(f"           Below that means residues changed that were meant to be frozen.")
    print(f"  flexID%  how much of the channel lining MPNN actually rewrote.")


if __name__ == "__main__":
    main()
