#!/usr/bin/env python3
"""
fix_pdb_chains.py — prepare a raw crystal-structure PDB for the RFD3 pipeline.

  - HEM  -> chain B (heme cofactor on its own chain)
  - UNL  -> chain C, record type HETATM, unique atom names (N1, C1..Cn, O1..)
  - MG / CL / HOH  -> removed (crystallisation additives, not part of design)
  - protein (chain A), CRYST1, TER, CONECT, END  -> kept unchanged

Usage:
  python fix_pdb_chains.py input.pdb output_fixed.pdb
"""
import sys

if len(sys.argv) != 3:
    sys.exit("Usage: python fix_pdb_chains.py <input.pdb> <output_fixed.pdb>")

inp, outp = sys.argv[1], sys.argv[2]

DROP_RESIDUES = {"MG", "CL", "HOH", "NA", "K", "SO4", "GOL", "EDO", "PO4"}

elem_count = {}   # per-element counter for renaming UNL atoms
out_lines = []
n_hem = n_unl = n_dropped = 0

with open(inp) as f:
    for line in f.rstrip("\n").split("\n") if False else f:
        rec = line[:6]

        if rec in ("ATOM  ", "HETATM"):
            resname = line[17:20].strip()

            if resname == "HEM":
                # heme -> chain B (column 22, 0-indexed 21)
                line = line[:21] + "B" + line[22:]
                out_lines.append(line)
                n_hem += 1

            elif resname in DROP_RESIDUES:
                n_dropped += 1
                continue

            elif resname == "UNL":
                # element symbol lives in cols 77-78; fall back to first
                # non-space char of the atom-name field if missing
                elem = line[76:78].strip() or line[12:16].strip()[0]
                elem_count[elem] = elem_count.get(elem, 0) + 1
                newname = f"{elem}{elem_count[elem]}"
                namefield = (" " + newname.ljust(3))[:4]   # cols 13-16
                # HETATM | serial | name | altLoc+resName+col21 | chain C | rest
                line = "HETATM" + line[6:12] + namefield + line[16:21] + "C" + line[22:]
                out_lines.append(line)
                n_unl += 1

            else:
                # protein atoms (chain A) — keep as-is
                out_lines.append(line)

        else:
            # CRYST1, TER, CONECT, END, etc. — keep
            out_lines.append(line)

with open(outp, "w") as f:
    f.writelines(l if l.endswith("\n") else l + "\n" for l in out_lines)

print(f"HEM atoms  -> chain B : {n_hem}")
print(f"UNL atoms  -> chain C : {n_unl}  (renamed {sorted(elem_count.items())})")
print(f"Dropped additives     : {n_dropped}")
print(f"Wrote {outp}")
