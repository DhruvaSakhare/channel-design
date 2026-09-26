#!/usr/bin/env python3
"""
config_local.py — single-GPU / no-scheduler overrides for config.py.

Everything scientific (FLEXIBLE_RESIDUES, catalytic pins, SMILES, cutoffs,
batch sizes) is inherited from config.py, so there is ONE place to edit an
experiment. This file only replaces the things that are specific to the DTU
cluster: install paths, checkpoints, and the scratch output root.

Used by scripts/run_local.py, which imports this module in place of
partial_diffusion.config before running the stage scripts.

Every value below can also be set from the environment, so you can keep the
file untouched and do e.g.:
    export RFD3_CKPT=/data/ckpt/rfd3_latest.ckpt
"""
import importlib
import os
from pathlib import Path

# Inherit the entire experiment definition from a base config. Defaults to
# config.py; set PIPELINE_BASE_CONFIG to target a different enzyme, e.g.
#     export PIPELINE_BASE_CONFIG=partial_diffusion.config_mroupo
BASE_CONFIG = os.environ.get("PIPELINE_BASE_CONFIG", "partial_diffusion.config")
_base = importlib.import_module(BASE_CONFIG)

# Equivalent to `from <base> import *`, but with a module name chosen at runtime.
# Everything below this line overrides what the base config set.
globals().update({k: v for k, v in vars(_base).items() if not k.startswith("_")})

PIPELINE_ROOT = _base.PIPELINE_ROOT
INPUT_PDB     = _base.INPUT_PDB
REPO_ROOT     = PIPELINE_ROOT.parent


def _env(name, default):
    return os.environ.get(name, default)


# ===========================================================================
# ● LOCAL INSTALL PATHS — point these at your own installs
# ===========================================================================
# rfd3 / mpnn are expected on $PATH (activate your env before running).
# If RF3 lives in its own environment, set RF3_ACTIVATE to a script that
# run_local.py will `source` before each fold; leave "" if RF3 is already on
# $PATH in the same env.
RFD3_CKPT    = _env("RFD3_CKPT",    str(REPO_ROOT / "ckpt" / "rfd3_latest.ckpt"))
MPNN_CKPT    = _env("MPNN_CKPT",    str(REPO_ROOT / "ckpt" / "ligandmpnn_v_32_010_25.pt"))
# All three checkpoints live together in ckpt/ — they are just weights, and
# keeping them in one place means nothing has to be configured after a copy.
# RF3_RELEASE is separate because it is the RF3 *software* tree (activate_env.sh,
# the modelhub package), which is machine-specific and cannot be copied.
RF3_CKPT     = _env("RF3_CKPT",     str(REPO_ROOT / "ckpt" / "rf3_latest.pt"))
RF3_RELEASE  = _env("RF3_RELEASE",  str(REPO_ROOT / "rf3" / "release"))
RF3_ACTIVATE = _env("RF3_ACTIVATE", str(Path(RF3_RELEASE) / "activate_env.sh"))

# The base config may carry an absolute MSA path. Look for the local copy
# next to the input PDB instead, using the name 00_make_msa.py writes:
# <pdb_stem>_A.a3m.gz beside it, then inputs/. Empty = single-sequence folding.
_msa_name = f"{Path(INPUT_PDB).stem}_A.a3m.gz"
_msa_default = next((p for p in (Path(INPUT_PDB).parent / _msa_name,
                                 REPO_ROOT / "inputs" / _msa_name)
                     if p.exists()), REPO_ROOT / "inputs" / _msa_name)
NATIVE_MSA_PATH = _env("NATIVE_MSA_PATH",
                       str(_msa_default) if _msa_default.exists() else "")

# Unused locally, but the stage scripts read them when building submit files.
QUEUE       = "local"
CPU_QUEUE   = "local"
CONDA_SH    = ""
PROTEIN_ENV = ""

# ===========================================================================
# ✗ DON'T EDIT — local output paths (mirror of the cluster layout)
# ===========================================================================
SHARED_ROOT   = Path(_env("PIPELINE_WORK_ROOT", str(REPO_ROOT / "work")))
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
    """Local re-implementation — config.make_workdirs() would create the
    cluster paths, since it closes over config.py's globals, not these."""
    if not SUBSTRATE_SMILES and not SUBSTRATE_CCD:
        raise RuntimeError("Set SUBSTRATE_SMILES or SUBSTRATE_CCD in config.py.")
    for d in (CONFIGS_DIR, SUBMIT_DIR, LOGS_DIR, CMDS_DIR,
              SCORES_DIR, DIFFUSION_DIR, MPNN_DIR, RF3_DIR, BEST_DIR):
        d.mkdir(parents=True, exist_ok=True)
