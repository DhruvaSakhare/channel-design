"""
mark_flexible.py — PyMOL helper to export a FLEXIBLE_RESIDUES list from a session.

Run this in your LOCAL PyMOL (GUI or `pymol -cq`), not on the cluster.

WORKFLOW
--------
1. Open your prepared enzyme structure in PyMOL (heme on chain B, substrate on
   chain C — the same PDB you'd feed the pipeline).
2. Select the residues you want to be FLEXIBLE (free to move + redesign) and name
   that selection `flexible`, e.g.:
       select flexible, chain A and resi 195+257-262+292+295+335-336
   (or click residues in the GUI, then rename the selection to `flexible`).
3. Load and run this file, then call the command:
       run mark_flexible.py
       mark_flexible
   Optional args:  mark_flexible <selection>, <chain>, <out_prefix>
       e.g.  mark_flexible flexible, A, PabUPO-II

OUTPUT (next to your PyMOL working dir)
    <prefix>.pdb        — the structure saved as PDB (feed this to the pipeline)
    <prefix>_flex.json  — {"input_pdb", "chain", "flexible_residues": [...]}

Then, on the cluster:
    python partial_diffusion/scripts/00_from_pymol.py <prefix>.pdb <prefix>_flex.json
"""
import json
import os

try:
    from pymol import cmd
except ImportError:  # allows importing the file outside PyMOL without crashing
    cmd = None


def mark_flexible(selection="flexible", chain="A", out_prefix=""):
    if cmd is None:
        raise RuntimeError("mark_flexible must be run inside PyMOL.")

    # Which object are we exporting? Take the object(s) the selection belongs to.
    objs = cmd.get_object_list(f"({selection})")
    if not objs:
        raise RuntimeError(
            f"No atoms in selection '{selection}'. Create it first, e.g.:\n"
            f"    select {selection}, chain {chain} and resi 195+257-262"
        )
    if len(objs) > 1:
        raise RuntimeError(f"Selection '{selection}' spans multiple objects {objs}; "
                           f"keep one structure loaded.")
    obj = objs[0]
    prefix = out_prefix or obj

    # Pull residue numbers of the flexible selection on the protein chain.
    resis = set()
    cmd.iterate(f"({selection}) and polymer and chain {chain} and name CA",
                "resis.add(resi)", space={"resis": resis})
    if not resis:
        # fall back to any atom if CA naming differs
        cmd.iterate(f"({selection}) and polymer and chain {chain}",
                    "resis.add(resi)", space={"resis": resis})

    flexible = sorted(int(r) for r in resis if r.lstrip("-").isdigit())
    if not flexible:
        raise RuntimeError(
            f"Selection '{selection}' contained no chain-{chain} protein residues. "
            f"Check the chain letter (arg 2).")

    pdb_path  = f"{prefix}.pdb"
    json_path = f"{prefix}_flex.json"
    cmd.save(pdb_path, obj)
    with open(json_path, "w") as fh:
        json.dump({"input_pdb": os.path.basename(pdb_path),
                   "chain": chain,
                   "flexible_residues": flexible}, fh, indent=2)

    print(f"[mark_flexible] object            : {obj}")
    print(f"[mark_flexible] chain             : {chain}")
    print(f"[mark_flexible] flexible residues : {len(flexible)}  {flexible}")
    print(f"[mark_flexible] wrote             : {pdb_path}")
    print(f"[mark_flexible] wrote             : {json_path}")
    print(f"[mark_flexible] next (on cluster) : "
          f"python partial_diffusion/scripts/00_from_pymol.py {pdb_path} {json_path}")


if cmd is not None:
    cmd.extend("mark_flexible", mark_flexible)
