"""
Every example config must point at a structure whose ligands are HETATM.

This is not pedantry about file format. Two of the bundled MroUPO structures
differ only in record type, and in the one that writes the substrate as ATOM
every ligand-aware step misses it: CAVER finds zero tunnels there and forty in
the other. One shipped config pointed at the wrong one. Nothing in the code
notices -- it just silently measures nothing -- so it is asserted here.
"""
import re
import subprocess
import sys

import pytest

from conftest import REPO_ROOT

CONFIG_DIR = REPO_ROOT / "enzyme_design" / "partial_diffusion" / "configs"
CONFIGS = sorted(CONFIG_DIR.glob("config_*.py"))

# Residue names that are cofactors or substrates, never protein.
LIGAND_RESNAMES = ("UNL", "UNK", "NNBT", "HEM")


def _input_pdb(module, tmp_path):
    code = (f"import importlib; print(importlib.import_module({module!r}).INPUT_PDB)")
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        env={"PYTHONPATH": str(REPO_ROOT / "enzyme_design"),
             "PIPELINE_WORK_ROOT": str(tmp_path),
             "PIPELINE_BASE_CONFIG": module,
             "PATH": "/usr/bin:/bin"},
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


@pytest.mark.parametrize("path", CONFIGS, ids=lambda p: p.stem)
def test_ligands_are_hetatm(path, tmp_path):
    pdb = _input_pdb(f"partial_diffusion.configs.{path.stem}", tmp_path)
    text = open(pdb).read()

    offenders = set()
    for line in text.splitlines():
        if not line.startswith("ATOM"):
            continue
        resname = line[17:20].strip()
        if resname in LIGAND_RESNAMES:
            offenders.add(resname)

    assert not offenders, (
        f"{path.name} -> {pdb}\n"
        f"  ligand(s) {sorted(offenders)} written as ATOM, not HETATM.\n"
        "  Ligand-aware steps will not see them and CAVER will find no tunnel.")
