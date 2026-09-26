"""
config_mroupo.py — MroUPO tunnel engineering (adapted from donatela's
mroupo_nnbt_helices_53_148_204_aggressive config for a local single-GPU test).

Same idea as config.py: partial diffusion + targeted remodel of the substrate
channel. Three helices lining the channel are made flexible; everything else is
held rigid and native.

Use with the local runner:
    export PIPELINE_BASE_CONFIG=partial_diffusion.config_mroupo
    python partial_diffusion/scripts/run_local.py --auto-msa --check

Differences from the config this was adapted from, all deliberate:
  1. Glu157 and Phe160 removed from FLEXIBLE_RESIDUES. They are catalytic pins,
     and _build_fixed_atoms/_build_catres only apply pins to residues NOT in the
     flexible list — so leaving them in silently discarded their _CATALYTIC_PINS
     entries and handed the distal acid-base Glu to MPNN to mutate.
  2. RFD3_N_BATCHES 10 -> 1: smoke test (10 backbones, 100 folds) before
     committing ~a day of serial GPU time to the full 100/1000.

Tags:  ★ EVERY RUN   ◆ PER EXPERIMENT   ● PER ENZYME   ✗ DON'T EDIT
"""
import os
from pathlib import Path

# ===========================================================================
# ★ EVERY RUN — who you are and a unique name for this run
# ===========================================================================
YOUR_NAME  = "dhruva"                                  # ★
EXPERIMENT = "mroupo_helices_53_148_204_smoke01"       # ★ UNIQUE per run

# ===========================================================================
# ● PER ENZYME — input structure and ligands
# ===========================================================================
PIPELINE_ROOT = Path(__file__).resolve().parent
LIB_ROOT      = PIPELINE_ROOT.parent / "lib"

# Verified: chain A = 234 residues (1-234), HEM on chain B, UNL on chain C,
# no alternate conformations.
#
# NOTE: this is fix_pdb_chains.py's output, not mroupo_nnbt_docked_clean.pdb.
# In that file UNL was written as ATOM rather than HETATM, so the pipeline's
# ligand checks could not see it (and --trim would have dropped the substrate).
# The fix changes ONLY the record type — atom names, chains and chain A's
# residue numbering are identical.
INPUT_PDB = str(PIPELINE_ROOT.parent / "inputs" / "mroupo_nnbt_fixed.pdb")  # ●

HEME_NAME      = "HEM"    # ●
SUBSTRATE_NAME = "UNL"    # ●
LIGAND_NAMES   = [HEME_NAME, SUBSTRATE_NAME]

# ===========================================================================
# ◆ PER EXPERIMENT — THE MAIN KNOB: which residues are allowed to change
# ===========================================================================
# The three channel-lining helices. 157 (distal Glu) and 160 (Phe) are
# deliberately EXCLUDED from the middle helix — see _CATALYTIC_PINS below.
FLEXIBLE_RESIDUES = [                          # ◆
    53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66,          # first helix
    148, 149, 150, 151, 152, 153, 154, 155, 156,                     # third (left) helix,
    158, 159, 161, 162, 163, 164,                                    #   157/160 held back
    204, 205, 206, 207, 208, 209, 210, 211, 212, 213, 214, 215, 216, 217, 218,  # fourth helix
]

# ● Catalytic / structural residues held rigid, with EXTRA sidechain atoms
# pinned. A residue listed here MUST NOT appear in FLEXIBLE_RESIDUES — the
# builders below skip flexible residues entirely, so a pin on a flexible
# residue is silently ignored and MPNN is free to mutate it.
_CATALYTIC_PINS = {                            # ●
    17:  "N,CA,C,O,CB,SG",   # proximal Cys — heme thiolate, 5th Fe ligand
    86:  "N,CA,C,O,CB",      # distal His — acid-base catalysis
    157: "N,CA,C,O,CB",      # distal Glu — H2O2 activation
    160: "N,CA,C,O,CB",      # Phe — orients substrate toward heme
}

# ◆ How aggressive the remodel is. 3-5 gentle, 8-12 more backbone freedom.
# 15 is past the documented range and 46 flexible residues is ~20% of the
# protein — expect a low pass rate. That is the point of the experiment, but
# it is also why PLDDT_CUT below is worth watching.
PARTIAL_T = 15  # ◆ Å

# ◆ How many backbones (total = BATCH_SIZE × N_BATCHES)
RFD3_BATCH_SIZE = 10   # backbones per GPU call
RFD3_N_BATCHES  = 1    # ◆ SMOKE TEST — 1 → 10 backbones. Set to 10 for production.

# ---------------------------------------------------------------------------
# ✗ DON'T EDIT — helpers that build CATRES / FIXED_ATOMS / CONTIG for you
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

# Guard against the failure mode this config was adapted to fix.
_pinned_but_flexible = sorted(set(_CATALYTIC_PINS) & set(FLEXIBLE_RESIDUES))
if _pinned_but_flexible:
    raise RuntimeError(
        f"Residues {_pinned_but_flexible} are in both _CATALYTIC_PINS and "
        f"FLEXIBLE_RESIDUES. Pins on flexible residues are silently discarded — "
        f"RFD3 would move them and MPNN would redesign them. Remove them from "
        f"one list or the other.")

# ---------------------------------------------------------------------------
# ✗ DON'T EDIT — run snapshot override
# ---------------------------------------------------------------------------
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
CONTIG      = _overrides["CONTIG"]      if (_SNAPSHOT_PATH and "CONTIG" in _overrides)      else _auto_contig(INPUT_PDB)  # ◆

# ===========================================================================
# ● PER ENZYME — substrate chemistry for RF3
# ===========================================================================
HEME_CCD         = "HEM"
SUBSTRATE_SMILES = "CC1CCC(N(C[C@@H](C)O)C[C@@H](C)O)CC1"  # ● NNBT
SUBSTRATE_CCD    = ""    # ●

# ===========================================================================
# ◆ PER EXPERIMENT — pass/fail thresholds used to pick best_designs
# ===========================================================================
# These assume MSA-conditioned folding. Single-sequence pLDDT runs lower and
# 0.85 would reject nearly everything — build the MSA (--auto-msa) or lower it.
PLDDT_CUT = 0.85   # ◆
PAE_CUT   = 6.0    # ◆
IPSAE_CUT = 0.55   # ◆

# ✗ DON'T EDIT — RF3 chain order (A=enzyme, B=heme, C=substrate)
RF3_ENZYME_CHAIN    = "A_1"
RF3_HEME_CHAIN      = "B_1"
RF3_SUBSTRATE_CHAIN = "C_1"

# ===========================================================================
# ◆ PER EXPERIMENT — scale
# ===========================================================================
MPNN_BATCH_SIZE        = 10   # ◆
MPNN_NUMBER_OF_BATCHES = 1    # ◆
RF3_NUM_STEPS          = 100  # ◆
RF3_GROUP_SIZE         = 10

# ===========================================================================
# ● Cluster paths — overridden by config_local.py when running locally
# ===========================================================================
QUEUE       = "gpua100"
CPU_QUEUE   = "hpc"
CONDA_SH    = "/dtu/blackhole/00/c27666/miniforge3/etc/profile.d/conda.sh"      # ✗
PROTEIN_ENV = "/dtu/blackhole/00/c27666/miniforge3/envs/protein-design"        # ✗
RFD3_CKPT   = "/dtu/projects/dbl/foundry/ckpt/rfd3_latest.ckpt"                 # ✗
MPNN_CKPT   = "/dtu/projects/dbl/foundry/ckpt/ligandmpnn_v_32_010_25.pt"        # ✗
RF3_RELEASE = "/dtu/projects/dbl/rf3/release"                                   # ✗
RF3_CKPT    = "/dtu/projects/dbl/rf3/release/ckpt/rf3_latest.pt"                # ✗
# Built by 00_make_msa.py; discovered by convention so this works unchanged on
# the cluster as well as locally. "" = single-sequence folding (see PLDDT_CUT).
_msa_default    = PIPELINE_ROOT.parent / "inputs" / f"{Path(INPUT_PDB).stem}_A.a3m.gz"
NATIVE_MSA_PATH = str(_msa_default) if _msa_default.exists() else ""

# ---------------------------------------------------------------------------
# ✗ DON'T EDIT — derived output paths
# ---------------------------------------------------------------------------
if not YOUR_NAME or YOUR_NAME == "your_name":
    raise RuntimeError("Set YOUR_NAME in config.py before running.")

SHARED_ROOT = Path("/work3/s215098/BioBuilders2026")
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
