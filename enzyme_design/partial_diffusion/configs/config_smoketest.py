"""
config_smoketest.py — fast end-to-end flow check: 1 backbone x 1 sequence x 1 fold.

Not a real design run. Purpose is only to confirm every stage (MSA -> RFD3 ->
MPNN -> RF3 -> score -> collect) actually completes and produces a scored
design, before committing GPU time to a full batch. Uses the real native MSA
(auto-built by 00_submit_all.py --auto-msa if missing) so RF3 folds properly
and pLDDT is meaningful, not just single-sequence noise.

To use — no config.py write access needed, every stage script now honors
PIPELINE_BASE_CONFIG directly:
    export PIPELINE_BASE_CONFIG=partial_diffusion.dhruva_configs.config_smoketest
    python partial_diffusion/scripts/00_submit_all.py --auto-msa
"""
import os
from pathlib import Path

YOUR_NAME  = "example"
EXPERIMENT = "smoketest_flow_check_02"   # bump the number to rerun clean

PIPELINE_ROOT = Path(__file__).resolve().parent.parent
LIB_ROOT      = PIPELINE_ROOT.parent / "lib"

INPUT_PDB = str(PIPELINE_ROOT.parent / "inputs" / "PabUPO-II_withHEMEFE_and_NNBT.pdb")

HEME_NAME      = "HEM"
SUBSTRATE_NAME = "UNL"
LIGAND_NAMES   = [HEME_NAME, SUBSTRATE_NAME]

# Auto-detect the standard MSA location (same rule config.py itself uses).
# If it's missing, `00_submit_all.py --auto-msa` builds it fresh before
# queueing anything — that's part of what this smoke test is meant to prove.
_msa_default = PIPELINE_ROOT.parent / "inputs" / f"{Path(INPUT_PDB).stem}_A.a3m.gz"
NATIVE_MSA_PATH = str(_msa_default) if _msa_default.exists() else ""

FLEXIBLE_RESIDUES = [
    92, 195, 207,
    255, 256, 257, 258, 259, 260, 261, 262, 263, 264,
    292, 293, 294, 295,
    334, 335, 336,
]

_CATALYTIC_PINS = {
    52:  "N,CA,C,O,CB,SG",
    85:  "N,CA,C,O,CB",
    137: "N,CA,C,O,CB",
    215: "N,CA,C,O,CB",
    205: "N,CA,C,O,CB",
    212: "N,CA,C,O,CB",
    296: "N,CA,C,O,CB,SG",
    339: "N,CA,C,O,CB,SG",
}

PARTIAL_T = 10

# --- THE KNOBS THAT MAKE THIS A SMOKE TEST: 1 x 1 x 1 = 1 folded design ---
RFD3_BATCH_SIZE = 1
RFD3_N_BATCHES  = 1
MPNN_BATCH_SIZE = 1
MPNN_NUMBER_OF_BATCHES = 1
RF3_NUM_STEPS   = 50   # fast draft, not production (100)
RF3_GROUP_SIZE  = 10   # irrelevant at n=1, leave as-is

# ---------------------------------------------------------------------------
# ✗ DON'T EDIT — same helpers/derivation logic as config.py
# ---------------------------------------------------------------------------
def _chain_resids(pdb_path, chain="A"):
    ids = set()
    with open(pdb_path) as f:
        for line in f:
            if line[:4] == "ATOM" and line[21] == chain:
                ids.add(int(line[22:26].strip()))
    if not ids:
        raise RuntimeError(f"No ATOM records for chain {chain} in {pdb_path}")
    return sorted(ids)

def _build_fixed_atoms(pdb_path, flexible, chain="A"):
    flex = set(flexible)
    return {f"{chain}{r}": _CATALYTIC_PINS.get(r, "N,CA,C,O")
            for r in _chain_resids(pdb_path, chain) if r not in flex}

def _build_catres(pdb_path, flexible, chain="A"):
    flex = set(flexible)
    return [f"{chain}{r}" for r in _chain_resids(pdb_path, chain) if r not in flex]

def _auto_contig(pdb_path, chain="A"):
    r = _chain_resids(pdb_path, chain)
    return f"{chain}{r[0]}-{r[-1]}"

_SNAPSHOT_PATH = os.environ.get("PIPELINE_RUN_CONFIG")
if _SNAPSHOT_PATH:
    import json as _json
    with open(_SNAPSHOT_PATH) as _f:
        _overrides = _json.load(_f)
    _PATH_KEYS = {
        "WORK", "CONFIGS_DIR", "SUBMIT_DIR", "LOGS_DIR", "CMDS_DIR",
        "SCORES_DIR", "DIFFUSION_DIR", "MPNN_DIR", "RF3_DIR", "BEST_DIR",
    }
    for _k, _v in _overrides.items():
        globals()[_k] = Path(_v) if _k in _PATH_KEYS else _v

CATRES      = _overrides["CATRES"]      if (_SNAPSHOT_PATH and "CATRES" in _overrides)      else _build_catres(INPUT_PDB, FLEXIBLE_RESIDUES)
FIXED_ATOMS = _overrides["FIXED_ATOMS"] if (_SNAPSHOT_PATH and "FIXED_ATOMS" in _overrides) else _build_fixed_atoms(INPUT_PDB, FLEXIBLE_RESIDUES)
CONTIG      = _overrides["CONTIG"]      if (_SNAPSHOT_PATH and "CONTIG" in _overrides)      else _auto_contig(INPUT_PDB)

HEME_CCD         = "HEM"
SUBSTRATE_SMILES = "CC1CCC(N(C[C@@H](C)O)C[C@@H](C)O)CC1"
SUBSTRATE_CCD    = ""

# Same thresholds as the real experiment — MSA-folded pLDDT should be
# meaningful here, not single-sequence noise.
PLDDT_CUT = 0.80
PAE_CUT   = 8.0
IPSAE_CUT = 0.50

RF3_ENZYME_CHAIN    = "A_1"
RF3_HEME_CHAIN      = "B_1"
RF3_SUBSTRATE_CHAIN = "C_1"

QUEUE       = "gpua100"
CPU_QUEUE   = "hpc"
# Install paths, checkpoints and queue names live in site.py, not here —
# an experiment is portable, a filesystem is not. Override from the
# environment (see envs/design.md), never by editing this block.  # ✗
from partial_diffusion.site import (  # noqa: E402
    CONDA_SH, MPNN_CKPT, PROTEIN_ENV, RF3_CKPT, RF3_RELEASE, RFD3_CKPT,
    SHARED_ROOT,
)

if not YOUR_NAME or YOUR_NAME == "your_name":
    raise RuntimeError("Set YOUR_NAME in config.py before running.")

if not (_SNAPSHOT_PATH and "WORK" in _overrides):
    WORK          = SHARED_ROOT / YOUR_NAME / EXPERIMENT
    CONFIGS_DIR   = WORK / "configs"
    SUBMIT_DIR    = WORK / "submit"
    LOGS_DIR      = WORK / "logs"
    CMDS_DIR      = WORK / "cmds"
    SCORES_DIR    = WORK / "scores"
    DIFFUSION_DIR = WORK / "diffusion_out"
    MPNN_DIR      = WORK / "mpnn_out"
    RF3_DIR       = WORK / "rf3_out"
    BEST_DIR      = WORK / "best_designs"

def make_workdirs():
    if not SUBSTRATE_SMILES and not SUBSTRATE_CCD:
        raise RuntimeError("Set SUBSTRATE_SMILES or SUBSTRATE_CCD in config.py.")
    for d in (CONFIGS_DIR, SUBMIT_DIR, LOGS_DIR, CMDS_DIR,
              SCORES_DIR, DIFFUSION_DIR, MPNN_DIR, RF3_DIR, BEST_DIR):
        d.mkdir(parents=True, exist_ok=True)
