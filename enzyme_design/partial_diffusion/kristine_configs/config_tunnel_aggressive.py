"""
config.py (partial diffusion) — PabUPO-II TUNNEL WIDENING, AGGRESSIVE variant.

Same hypothesis and same "keep most fixed, flex only the channel" mechanism as
the conservative config (see FLEXIBLE_RESIDUES below), but here MORE of the
channel is freed and PARTIAL_T is higher, so the entrance and middle can open up
more (and the gating residues V92/I207 are explored). The heme-proximal catalytic
core and structural disulfides are STILL held rigid in structure and sequence.

Expect a somewhat lower backbone yield than the conservative run — freeing more
residues at higher noise makes more broken backbones (filtered out downstream).
Select winners with CAVER (wide mouth + narrow gate).
"""
import os
from pathlib import Path

YOUR_NAME  = "kristine"
EXPERIMENT = "pab_upo_II_tunnel_aggressive_01"

# .parent.parent, NOT .parent — this file lives one level deeper than config.py
# (in a *_configs/ subfolder), so it needs an extra hop to reach
# partial_diffusion/. With only one .parent, INPUT_PDB resolves to
# partial_diffusion/inputs/ instead of the repo's inputs/ and the config raises
# FileNotFoundError on import.
PIPELINE_ROOT = Path(__file__).resolve().parent.parent
LIB_ROOT      = PIPELINE_ROOT.parent / "lib"
INPUT_PDB = str(PIPELINE_ROOT.parent / "inputs" / "PabUPO-II_withHEMEFE_and_NNBT.pdb")

HEME_NAME      = "HEM"
SUBSTRATE_NAME = "UNL"
LIGAND_NAMES   = [HEME_NAME, SUBSTRATE_NAME]

# ---------------------------------------------------------------------------
# THE ONLY KNOB — residues allowed to move (RFD3) and be redesigned (MPNN).
# Everything not listed here is held rigid in structure AND sequence.
# Aggressive set: the conservative residues + the gating pair (V92, I207) + a
# wider window around the entrance helix and the middle loop.
# ---------------------------------------------------------------------------
FLEXIBLE_RESIDUES = [
    92,                                            # gating (substitutes AaeUPO F76)
    195,                                           # entrance
    207,                                           # gating (substitutes AaeUPO F191)
    255, 256, 257, 258, 259, 260, 261, 262, 263, 264,  # middle constriction loop + flanks
    292, 293, 294, 295,                            # hydrophobic-helix narrowers
    334, 335, 336,                                 # entrance narrowers (F336 region)
]

_CATALYTIC_PINS = {
    52:  "N,CA,C,O,CB,SG",   # proximal catalytic Cys (heme thiolate)
    85:  "N,CA,C,O,CB",      # aromatic tripod (orients substrate to heme)
    137: "N,CA,C,O,CB",
    215: "N,CA,C,O,CB",
    205: "N,CA,C,O,CB",      # acid-base pair (H2O2 cleavage)
    212: "N,CA,C,O,CB",
    296: "N,CA,C,O,CB,SG",   # disulfide (stabilises active-site frame)
    339: "N,CA,C,O,CB,SG",
}

PARTIAL_T = 10  # Å  — more backbone freedom for the flexible channel residues

RFD3_BATCH_SIZE = 10
RFD3_N_BATCHES  = 10   # 100 backbones (expect lower pass yield than conservative)

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
    fixed = {}
    for r in _chain_resids(pdb_path, chain):
        if r in flex:
            continue
        fixed[f"{chain}{r}"] = _CATALYTIC_PINS.get(r, "N,CA,C,O")
    return fixed

def _build_catres(pdb_path, flexible, chain="A"):
    flex = set(flexible)
    return [f"{chain}{r}" for r in _chain_resids(pdb_path, chain) if r not in flex]

def _auto_contig(pdb_path, chain="A"):
    r = _chain_resids(pdb_path, chain)
    return f"{chain}{r[0]}-{r[-1]}"

# ---------------------------------------------------------------------------
# Run snapshot override — DO NOT EDIT
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
CONTIG      = _overrides["CONTIG"]      if (_SNAPSHOT_PATH and "CONTIG" in _overrides)      else _auto_contig(INPUT_PDB)

HEME_CCD         = "HEM"
SUBSTRATE_SMILES = "CC1CCC(N(C[C@@H](C)O)C[C@@H](C)O)CC1"
SUBSTRATE_CCD    = ""

PLDDT_CUT = 0.70
PAE_CUT   = 12.0
IPSAE_CUT = 0.40

RF3_ENZYME_CHAIN    = "A_1"
RF3_HEME_CHAIN      = "B_1"
RF3_SUBSTRATE_CHAIN = "C_1"

MPNN_BATCH_SIZE        = 10
MPNN_NUMBER_OF_BATCHES = 1
RF3_NUM_STEPS          = 100
RF3_GROUP_SIZE         = 10

QUEUE       = "gpua100"   # GPU queue: RFD3 / MPNN / RF3 folding
CPU_QUEUE   = "hpc"       # CPU queue: prep / launcher / scoring — verify with `bqueues`
CONDA_SH    = "/dtu/blackhole/00/c27666/miniforge3/etc/profile.d/conda.sh"
PROTEIN_ENV = "/dtu/blackhole/00/c27666/miniforge3/envs/protein-design"
RFD3_CKPT   = "/dtu/projects/dbl/foundry/ckpt/rfd3_latest.ckpt"
MPNN_CKPT   = "/dtu/projects/dbl/foundry/ckpt/ligandmpnn_v_32_010_25.pt"
RF3_RELEASE = "/dtu/projects/dbl/rf3/release"
RF3_CKPT    = "/dtu/projects/dbl/rf3/release/ckpt/rf3_latest.pt"

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
