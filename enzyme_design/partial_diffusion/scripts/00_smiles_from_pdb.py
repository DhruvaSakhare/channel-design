#!/usr/bin/env python3
"""
00_smiles_from_pdb.py — extract a SMILES string for the substrate from the input PDB.

Uses RDKit to read the substrate HETATM records (identified by SUBSTRATE_NAME in
config.py) and generate a canonical SMILES string. Copy the output directly into
SUBSTRATE_SMILES in partial_diffusion/config.py.

Run from enzyme_design_hpc/:
  python partial_diffusion/scripts/00_smiles_from_pdb.py

Requirements:
  - Conda environment must be active (it includes RDKit)
  - The substrate HETATM records must have CONECT lines in the PDB
    (the Pada1_withHEMEFE_and_NNBT.pdb already has these)
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import partial_diffusion.config as C

try:
    from rdkit import Chem
except ImportError:
    sys.exit(
        "RDKit not found. Activate the conda environment first:\n"
        "  source /dtu/blackhole/00/c27666/miniforge3/etc/profile.d/conda.sh\n"
        "  conda activate /dtu/blackhole/00/c27666/miniforge3/envs/protein-design"
    )


def extract_substrate(pdb_path, resname):
    """Return HETATM lines and relevant CONECT lines for the given residue name."""
    hetatm_lines = []
    atom_serials = set()
    all_conect = []

    with open(pdb_path) as f:
        for line in f:
            rec = line[:6].strip()
            if rec == "HETATM" and line[17:20].strip() == resname:
                hetatm_lines.append(line)
                atom_serials.add(line[6:11].strip())
            elif rec == "CONECT":
                all_conect.append(line)

    # Keep only CONECT records that reference substrate atoms
    conect_lines = [
        l for l in all_conect
        if any(tok in atom_serials for tok in l.split()[1:])
    ]
    return hetatm_lines, conect_lines


def main():
    resname  = C.SUBSTRATE_NAME
    pdb_path = C.INPUT_PDB

    print(f"Input PDB  : {pdb_path}")
    print(f"Substrate  : '{resname}'  (SUBSTRATE_NAME in config.py)\n")

    hetatm_lines, conect_lines = extract_substrate(pdb_path, resname)

    if not hetatm_lines:
        sys.exit(
            f"No HETATM records found for residue name '{resname}'.\n"
            "Check that SUBSTRATE_NAME in config.py matches the PDB exactly."
        )

    print(f"Found {len(hetatm_lines)} substrate atoms.")

    if not conect_lines:
        print(
            "Warning: no CONECT records found for the substrate.\n"
            "RDKit needs bond information to build the molecule — SMILES may be wrong.\n"
            "Consider adding CONECT records in PyMOL or look up the SMILES on PubChem.\n"
        )

    # Write a temporary mini-PDB with just the substrate
    with tempfile.NamedTemporaryFile(mode="w", suffix=".pdb", delete=False) as tmp:
        tmp.writelines(hetatm_lines)
        tmp.writelines(conect_lines)
        tmp.write("END\n")
        tmp_path = tmp.name

    mol = Chem.MolFromPDBFile(tmp_path, removeHs=True, sanitize=True)

    if mol is None:
        # Retry without sanitization to get a more helpful error
        mol = Chem.MolFromPDBFile(tmp_path, removeHs=True, sanitize=False)
        if mol is None:
            Path(tmp_path).unlink(missing_ok=True)
            sys.exit(
                "RDKit could not parse the substrate atoms.\n"
                "Make sure CONECT records are present and the atom coordinates are valid."
            )
        try:
            Chem.SanitizeMol(mol)
        except Exception as e:
            print(f"Warning: RDKit sanitization issue ({e}). SMILES may be approximate.")

    Path(tmp_path).unlink(missing_ok=True)

    smiles = Chem.MolToSmiles(mol)

    print(f"\nCanonical SMILES:\n  {smiles}")
    print(f"\nPaste this into partial_diffusion/config.py:")
    print(f'  SUBSTRATE_SMILES = "{smiles}"')
    print()


if __name__ == "__main__":
    main()
