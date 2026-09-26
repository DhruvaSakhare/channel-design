#!/usr/bin/env python3
"""
00_from_pymol.py — turn a PyMOL export into a ready-to-run config.py.

Takes the two files produced by `mark_flexible.py` in PyMOL (a PDB and a
<name>_flex.json listing the flexible residues) and writes a config.py from
config_template.py with FLEXIBLE_RESIDUES, INPUT_PDB (and optionally EXPERIMENT
/ YOUR_NAME / substrate) filled in. The PDB is copied into ../inputs/.

Usage:
  python partial_diffusion/scripts/00_from_pymol.py <structure.pdb> <structure_flex.json> \
      [--experiment NAME] [--your-name NAME] \
      [--substrate-name UNL] [--substrate-smiles "CC..."] [--force]

Then just:
  python partial_diffusion/scripts/00_prep_pdb.py --check
  python partial_diffusion/scripts/00_submit_all.py
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

PARTIAL_DIFFUSION = Path(__file__).resolve().parents[1]     # .../partial_diffusion
TEMPLATE = PARTIAL_DIFFUSION / "config_template.py"
CONFIG   = PARTIAL_DIFFUSION / "config.py"
INPUTS   = PARTIAL_DIFFUSION.parent / "inputs"


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("pdb", help="PDB exported from PyMOL (mark_flexible)")
    p.add_argument("flex_json", help="<name>_flex.json exported from PyMOL")
    p.add_argument("--experiment", default=None, help="EXPERIMENT name for the run")
    p.add_argument("--your-name", default=None, help="YOUR_NAME (output folder owner)")
    p.add_argument("--substrate-name", default=None, help="SUBSTRATE_NAME in the PDB")
    p.add_argument("--substrate-smiles", default=None, help="SUBSTRATE_SMILES")
    p.add_argument("--force", action="store_true",
                   help="Overwrite an existing config.py")
    return p.parse_args()


def replace_assignment(text, varname, new_rhs):
    """Replace `VAR = <...>` up to the end of that logical statement.

    Handles a single-line RHS or a bracketed multi-line list (FLEXIBLE_RESIDUES).
    Keeps any trailing inline comment that was on the *first* line removed.
    """
    # Multi-line list form: VAR = [ ... ]
    list_pat = re.compile(rf"^{re.escape(varname)}\s*=\s*\[.*?\]", re.DOTALL | re.MULTILINE)
    if list_pat.search(text):
        return list_pat.sub(f"{varname} = {new_rhs}", text, count=1)
    # Single-line form: VAR = ...   (stop at end of line)
    line_pat = re.compile(rf"^{re.escape(varname)}\s*=.*$", re.MULTILINE)
    if not line_pat.search(text):
        sys.exit(f"Could not find `{varname} = ...` in {TEMPLATE.name}")
    return line_pat.sub(f"{varname} = {new_rhs}", text, count=1)


def main():
    args = parse_args()
    pdb = Path(args.pdb)
    flex_json = Path(args.flex_json)
    for f in (pdb, flex_json, TEMPLATE):
        if not f.exists():
            sys.exit(f"Not found: {f}")
    if CONFIG.exists() and not args.force:
        sys.exit(f"{CONFIG} already exists — pass --force to overwrite (back it up first).")

    data = json.loads(flex_json.read_text())
    flexible = data.get("flexible_residues", [])
    chain = data.get("chain", "A")
    if not flexible:
        sys.exit("flexible_residues is empty in the JSON — nothing to configure.")
    if chain != "A":
        print(f"  NOTE: flexible residues are on chain {chain}; the pipeline assumes "
              f"the protein is chain A. Make sure your PDB uses chain A for the enzyme.")

    # 1. copy the structure into inputs/
    INPUTS.mkdir(exist_ok=True)
    dest_pdb = INPUTS / pdb.name
    shutil.copy2(pdb, dest_pdb)

    # sanity: warn if it doesn't look like a prepped 3-chain structure
    chains = set()
    heme = substrate = False
    for line in dest_pdb.read_text().splitlines():
        if line[:6] in ("ATOM  ", "HETATM"):
            chains.add(line[21])
            rn = line[17:20].strip()
            if rn in ("HEM", "HEC", "HEA"): heme = True
    if not heme:
        print("  WARNING: no HEM/HEC/HEA HETATM found — is the heme present and named?")
    if len(chains) < 2:
        print(f"  WARNING: only chain(s) {sorted(chains)} present — expected protein + "
              f"heme (+ substrate) on separate chains. Prep the PDB first if needed.")

    # 2. build config.py from the template
    text = TEMPLATE.read_text()
    flat = "[" + ", ".join(str(r) for r in flexible) + "]"
    text = replace_assignment(text, "FLEXIBLE_RESIDUES", flat)
    text = replace_assignment(
        text, "INPUT_PDB",
        f'str(PIPELINE_ROOT.parent / "inputs" / "{pdb.name}")')
    if args.experiment:
        text = replace_assignment(text, "EXPERIMENT", f'"{args.experiment}"')
    if args.your_name:
        text = replace_assignment(text, "YOUR_NAME", f'"{args.your_name}"')
    if args.substrate_name:
        text = replace_assignment(text, "SUBSTRATE_NAME", f'"{args.substrate_name}"')
    if args.substrate_smiles:
        text = replace_assignment(text, "SUBSTRATE_SMILES", f'"{args.substrate_smiles}"')

    CONFIG.write_text(text)

    print(f"\n  Wrote {CONFIG}")
    print(f"  INPUT_PDB         -> inputs/{pdb.name}")
    print(f"  FLEXIBLE_RESIDUES -> {len(flexible)} residues: {flexible}")
    print("\n  Next:")
    print("    python partial_diffusion/scripts/00_prep_pdb.py --check")
    print("    python partial_diffusion/scripts/00_submit_all.py"
          + (f" --experiment {args.experiment}" if args.experiment else ""))
    print("\n  Review config.py first — set YOUR_NAME / EXPERIMENT / SUBSTRATE_SMILES "
          "if you didn't pass them as flags.")


if __name__ == "__main__":
    main()
