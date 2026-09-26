# Shared settings for the LSF job scripts. Sourced by every script.
# Edit the paths below; nothing else should need changing.
#
# Every value uses ${VAR:-default}, so anything can be overridden from the
# environment. bsub propagates the submitting environment to array tasks, which
# is how submit_all.sh redirects a test run into its own WORK dir.

# Root of a shared team tree, if you have one. On a cluster this is usually
# scratch owned by one person, so do not build it out of $USER -- set it
# explicitly. The default is the checkout itself, which works out of the box.
TEAM="${TEAM:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

# Where the code lives.
PROJECT="${PROJECT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

# Where outputs go (~5-15 MB per structure, so ~10 GB for 1000).
# Inside a shared tree the files are still owned by you and count against your
# own quota, so point this at your own space if that is tight:
#   WORK=/scratch/$USER/channel_discovery ./submit_all.sh
WORK="${WORK:-$TEAM/work/channel_discovery_runs}"

# Your receptor structures (.pdb or .cif). Set this to wherever they actually
# are; the bundled reference crystals are a working default for a first run.
INPUTS="${INPUTS:-$PROJECT/fpocket_pipeline/inputs}"

# CAVER stage input. run_batch.py globs *.pdb only, so CIF inputs are converted
# here once by 20_collectA.sh (via caver_pipeline/python_scripts/cif_to_pdb.py).
# For .pdb inputs this ends up a straight copy.
PDB_INPUTS="${PDB_INPUTS:-$WORK/pdb_inputs}"

# Strip either extension from a structure path to get its stem.
stem_of() { s=$(basename "$1"); s="${s%.pdb}"; s="${s%.cif}"; printf '%s' "$s"; }

# Substrate to dock.
LIGAND="${LIGAND:-$PROJECT/fpocket_pipeline/ligands/NNBT.sdf}"

# Reference structures appended to EVERY run, on top of whatever --limit selects.
# They are characterised natural UPOs, so they calibrate the pocket thresholds
# (which were tuned on crystal structures) and act as anchors in the tunnel
# clustering: "this design clusters with 5OXU" is a much stronger statement than
# "these designs form 8 groups". find_reference_region.py also defaults to these
# exact stems. Set REFERENCES="" or pass --no-references to disable.
# Add your PabUPO-II parent here too — it is the direct before/after control.
REFERENCES="${REFERENCES:-$PROJECT/fpocket_pipeline/inputs}"

# Conda env to run in. This is the shared team env — anything installed into it
# affects teammates, so check what is already present before adding packages.
CONDA_ENV="${CONDA_ENV:-bio_docking}"

# Max array elements running at once. Keep this civil on a shared cluster.
# Each Stage A task takes 4 cores, so 40 here means 160 cores. Check your user
# limits (busers) before raising it.
MAXPAR="${MAXPAR:-40}"

# Number of tunnel-shape clusters. MUST be set explicitly at scale: the default
# in cluster_tunnels.py is len(structures)//3, which for 1000 inputs means 333
# clusters and a figure with 342 subplots. tab10 has only 10 distinct colours,
# so keep this <= 10. submit_all.sh scales it down automatically on small runs.
N_CLUSTERS="${N_CLUSTERS:-8}"

# Vina search effort. pipeline.py defaults to 32, which is thorough but slow.
# 8 is Vina's own default and the normal choice for a first-pass screen —
# re-dock the shortlist at 32 afterwards.
EXHAUSTIVENESS="${EXHAUSTIVENESS:-8}"

# Conda install root. Compute nodes run non-interactive shells that never source
# your profile, so `conda` is usually NOT on PATH there even when it works on the
# login node. Set this explicitly if the search below fails.
CONDA_BASE="${CONDA_BASE:-$TEAM/software/miniforge3}"

# A conda root is recognised by either its activation hook or an envs/ dir.
# Accepting envs/ alone matters because activate_env can fall back to putting
# <root>/envs/<name>/bin on PATH, which needs no conda machinery at all.
_is_conda_root() {
    [ -f "$1/etc/profile.d/conda.sh" ] || [ -d "$1/envs" ]
}

find_conda_base() {
    # Validate the configured root before trusting it, so a stale CONDA_BASE
    # falls through to the search rather than failing cryptically.
    if [ -n "$CONDA_BASE" ] && _is_conda_root "$CONDA_BASE"; then
        printf '%s' "$CONDA_BASE"; return 0
    fi
    if command -v conda >/dev/null 2>&1; then
        conda info --base; return 0
    fi
    for d in "$TEAM/software/miniforge3" "$TEAM/software/miniconda3" \
             "$TEAM/miniforge3" "$TEAM/miniconda3" \
             "$HOME/miniforge3" "$HOME/miniconda3" "$HOME/mambaforge" \
             "$HOME/anaconda3" "$HOME/conda" \
             "$TEAM/miniforge3" "$TEAM/miniconda3"; do
        if _is_conda_root "$d"; then
            printf '%s' "$d"; return 0
        fi
    done
    return 1
}

activate_env() {
    _base=$(find_conda_base) || {
        echo "ERROR: cannot find a conda installation." >&2
        echo "  Set CONDA_BASE in config.sh to your miniforge/miniconda root," >&2
        echo "  e.g. CONDA_BASE=\$HOME/miniforge3" >&2
        return 1
    }
    _envdir="$_base/envs/$CONDA_ENV"
    if [ ! -x "$_envdir/bin/python3" ]; then
        echo "ERROR: conda env '$CONDA_ENV' not found at $_envdir." >&2
        echo "  Run ./00_setup_env.sh first." >&2
        return 1
    fi

    # `conda activate` runs conda's own Python, which imports requests/urllib3
    # from the BASE install. On shared network storage that import intermittently
    # fails under array-job load (we saw FileNotFoundError on backports/zstd),
    # taking down otherwise healthy tasks. Try it, but fall back to putting the
    # env's bin on PATH directly — that is all this pipeline actually needs
    # (python3, fpocket) and it cannot fail.
    if [ -f "$_base/etc/profile.d/conda.sh" ]; then
        # shellcheck disable=SC1091
        . "$_base/etc/profile.d/conda.sh" 2>/dev/null && \
            conda activate "$CONDA_ENV" 2>/dev/null || true
    fi
    if [ "${CONDA_PREFIX:-}" != "$_envdir" ]; then
        echo "Note: conda activate unavailable; using PATH directly."
        PATH="$_envdir/bin:$PATH"
        export PATH CONDA_PREFIX="$_envdir"
    fi

    # Headless nodes have no display; matplotlib must not try to open one.
    export MPLBACKEND=Agg
}
