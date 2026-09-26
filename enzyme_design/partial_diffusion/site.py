#!/usr/bin/env python3
"""
The machine layer: install paths, checkpoints, and where runs are written.

Configs describe an *experiment* — which enzyme, which residues are flexible,
which substrate. This module describes a *machine*. Keeping them apart is why
an experiment config can be published without publishing somebody's home
directory, and why moving to a new cluster is one file rather than thirty.

Nothing here points at a particular cluster. Every value falls back to a
location inside the repository and can be overridden from the environment:

    export RFD3_CKPT=/shared/weights/rfd3_latest.ckpt
    export PIPELINE_WORK_ROOT=/scratch/$USER/runs

``envs/dtu-hpc.env.example`` holds the values the DTU HPC run used, and
``envs/design.md`` says where to obtain each checkpoint. The weights are not
redistributed with this repository.
"""
import os
from pathlib import Path

# enzyme_design/ — the parent of this package.
REPO_ROOT = Path(__file__).resolve().parents[1]


def _env(name, default):
    """Environment wins; otherwise the repo-relative default. Always a str."""
    value = os.environ.get(name)
    return value if value else str(default)


# --- conda -----------------------------------------------------------------
# Empty means "the right environment is already active", which is the normal
# case outside a batch scheduler.
CONDA_SH    = _env("CONDA_SH", "")
PROTEIN_ENV = _env("PROTEIN_ENV", "")

# --- model weights and software trees --------------------------------------
RFD3_CKPT   = _env("RFD3_CKPT",   REPO_ROOT / "ckpt" / "rfd3_latest.ckpt")
MPNN_CKPT   = _env("MPNN_CKPT",   REPO_ROOT / "ckpt" / "ligandmpnn_v_32_010_25.pt")
RF3_RELEASE = _env("RF3_RELEASE", REPO_ROOT / "rf3" / "release")
RF3_CKPT    = _env("RF3_CKPT",    Path(RF3_RELEASE) / "ckpt" / "rf3_latest.pt")

# --- scheduler -------------------------------------------------------------
# Queue names are site-specific; `bqueues` (LSF) lists what you have.
QUEUE     = _env("PIPELINE_QUEUE",     "gpua100")
CPU_QUEUE = _env("PIPELINE_CPU_QUEUE", "hpc")

# --- where runs are written ------------------------------------------------
# On a cluster this belongs on scratch, not in the repository.
SHARED_ROOT = Path(_env("PIPELINE_WORK_ROOT", REPO_ROOT / "work"))


def describe():
    """One line per resolved value — what a `--check` run should print."""
    names = ("CONDA_SH", "PROTEIN_ENV", "RFD3_CKPT", "MPNN_CKPT",
             "RF3_RELEASE", "RF3_CKPT", "QUEUE", "CPU_QUEUE", "SHARED_ROOT")
    out = []
    for name in names:
        value = globals()[name]
        origin = "env" if os.environ.get(name) else "default"
        out.append(f"  {name:14s} {str(value) or '(unset)':60s} [{origin}]")
    return "\n".join(out)


if __name__ == "__main__":
    print("channel-design site configuration:")
    print(describe())
