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
# Named explicitly, because explicit beats clever here: if two shared trees
# both contain rfd3_latest.ckpt, you want to say which one rather than have
# something pick for you.
#
# The defaults are inside the repository, which is where
# `./setup.sh --gpu --weights` puts them. Already have them elsewhere? Name
# them in envs/site.env (gitignored, so your filesystem stays yours):
#
#   export RFD3_CKPT=/shared/foundry/ckpt/rfd3_latest.ckpt
#   export MPNN_CKPT=/shared/foundry/ckpt/ligandmpnn_v_32_010_25.pt
#   export RF3_RELEASE=/shared/rf3/release
#   export RF3_CKPT=$RF3_RELEASE/ckpt/rf3_latest.pt
#
# RF3_RELEASE is the software tree, not just the weights, which is why it is
# separate. Check what resolved, and whether it exists:
#   python enzyme_design/partial_diffusion/site.py
RFD3_CKPT   = _env("RFD3_CKPT",   REPO_ROOT / "ckpt" / "rfd3_latest.ckpt")
MPNN_CKPT   = _env("MPNN_CKPT",   REPO_ROOT / "ckpt" / "ligandmpnn_v_32_010_25.pt")
RF3_RELEASE = _env("RF3_RELEASE", REPO_ROOT / "rf3" / "release")
RF3_CKPT    = _env("RF3_CKPT",    Path(RF3_RELEASE) / "ckpt" / "rf3_latest.pt")

# --- scheduler -------------------------------------------------------------
# Queue names are site-specific; `bqueues` (LSF) lists what you have.
#
# These are imported by every config, which is the only reason they do
# anything: the configs used to define their own literals instead, so these
# two were dead code and PIPELINE_QUEUE was silently ignored (KNOWN_ISSUES #9).
# tests/test_no_config_shadows_site.py keeps that from coming back.
#
# Precedence, lowest first: PIPELINE_QUEUE -> --queue.
#
# There is deliberately NO default. `gpua100` and `hpc` are DTU queue names;
# they mean nothing on another cluster, and a queue name is as site-specific
# as a path -- except that nothing here can check whether it exists, so a
# wrong one fails in the scheduler minutes later, or worse, succeeds on the
# wrong hardware. The old default also pointed at DTU's most contended queue
# (694 jobs deep at the time of writing) while this repository's own README
# said the two GPU queues are interchangeable: "if one is busy, try the
# other". Guessing on the user's behalf was not earning its keep.
#
# Empty is the unset signal. `00_submit_all.py` refuses to submit without it
# and names `bqueues`. Nothing else is affected: `run_local.py` has no
# scheduler, so a single-GPU run never needs a queue at all.
QUEUE     = _env("PIPELINE_QUEUE",     "")
CPU_QUEUE = _env("PIPELINE_CPU_QUEUE", "")

# --- where runs are written ------------------------------------------------
# On a cluster this belongs on scratch, not in the repository.
SHARED_ROOT = Path(_env("PIPELINE_WORK_ROOT", REPO_ROOT / "work"))


def describe():
    """One line per resolved value — what a `--check` run should print."""
    # Three of these are read from a differently named variable, so the origin
    # label has to look up the env var rather than the Python name -- it used
    # to report [default] for a QUEUE that had in fact been set.
    names = {
        "CONDA_SH":    "CONDA_SH",
        "PROTEIN_ENV": "PROTEIN_ENV",
        "RFD3_CKPT":   "RFD3_CKPT",
        "MPNN_CKPT":   "MPNN_CKPT",
        "RF3_RELEASE": "RF3_RELEASE",
        "RF3_CKPT":    "RF3_CKPT",
        "QUEUE":       "PIPELINE_QUEUE",
        "CPU_QUEUE":   "PIPELINE_CPU_QUEUE",
        "SHARED_ROOT": "PIPELINE_WORK_ROOT",
    }
    out = []
    for name, env_var in names.items():
        value = globals()[name]
        origin = "env" if os.environ.get(env_var) else "default"
        exists = ""
        if name.endswith(("_CKPT", "_RELEASE")) and str(value):
            exists = "" if Path(value).exists() else "   <-- DOES NOT EXIST"
        out.append(f"  {name:14s} {str(value) or '(unset)':60s} [{origin}]{exists}")
    return "\n".join(out)


if __name__ == "__main__":
    print("channel-design site configuration:")
    print(describe())
