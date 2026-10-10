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

# --- model weights ---------------------------------------------------------
# Checkpoints are large and are often already on a shared filesystem, so look
# for them rather than making you configure each one. The search is:
#
#   1. the specific variable, e.g. $RFD3_CKPT          -- always wins
#   2. each directory in $CKPT_SEARCH_PATH (colon-separated), in order
#   3. <repo>/ckpt/, where `foundry install base-models` puts them
#
# No cluster path is hardcoded here -- that would publish somebody's
# filesystem and is what tests/test_no_machine_paths.py exists to prevent. Put
# your own locations in $CKPT_SEARCH_PATH, e.g. in envs/site.env:
#
#   export CKPT_SEARCH_PATH=/shared/foundry/ckpt:/shared/other/ckpt
#
# Nothing is downloaded or created here. `./setup.sh --weights` fetches them if
# the search comes up empty.
CKPT_SEARCH_PATH = [
    Path(d) for d in os.environ.get("CKPT_SEARCH_PATH", "").split(os.pathsep) if d
]


def _find_ckpt(var, filename):
    """Resolve one checkpoint: explicit variable, then search path, then repo."""
    explicit = os.environ.get(var)
    if explicit:
        return explicit
    for directory in CKPT_SEARCH_PATH:
        candidate = directory / filename
        if candidate.is_file():
            return str(candidate)
    return str(REPO_ROOT / "ckpt" / filename)


RFD3_CKPT = _find_ckpt("RFD3_CKPT", "rfd3_latest.ckpt")
MPNN_CKPT = _find_ckpt("MPNN_CKPT", "ligandmpnn_v_32_010_25.pt")

# RF3 is a software tree, not just weights, so it is searched for separately:
# a directory containing ckpt/rf3_latest.pt.
def _find_rf3_release():
    explicit = os.environ.get("RF3_RELEASE")
    if explicit:
        return explicit
    for directory in CKPT_SEARCH_PATH:
        # Either <dir>/ckpt/rf3_latest.pt, or <dir> is itself a release tree.
        for candidate in (directory, directory.parent):
            if (candidate / "ckpt" / "rf3_latest.pt").is_file():
                return str(candidate)
    return str(REPO_ROOT / "rf3" / "release")


RF3_RELEASE = _find_rf3_release()
RF3_CKPT    = _find_ckpt("RF3_CKPT", "rf3_latest.pt")
if not Path(RF3_CKPT).is_file():
    # The usual place is inside the release tree.
    _in_release = Path(RF3_RELEASE) / "ckpt" / "rf3_latest.pt"
    if _in_release.is_file():
        RF3_CKPT = str(_in_release)

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
        if os.environ.get(name):
            origin = "env"
        elif any(str(value).startswith(str(d)) for d in CKPT_SEARCH_PATH):
            origin = "found"          # discovered via $CKPT_SEARCH_PATH
        elif str(value) and not str(value).startswith(str(REPO_ROOT)):
            origin = "found"
        else:
            origin = "default"
        exists = ""
        if name.endswith(("_CKPT", "_RELEASE")) and str(value):
            exists = "" if Path(value).exists() else "   <-- DOES NOT EXIST"
        out.append(f"  {name:14s} {str(value) or '(unset)':60s} [{origin}]{exists}")
    return "\n".join(out)


if __name__ == "__main__":
    print("channel-design site configuration:")
    print(describe())
