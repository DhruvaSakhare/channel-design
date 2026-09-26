#!/bin/sh
# Build the manifest and submit the whole chain with LSF dependencies.
# Run from a LOGIN node.
#
# Usage:
#   ./submit_all.sh [options] [N]
#
#   -w, --work DIR      where outputs go        (default: $WORK from config.sh)
#   -i, --inputs DIR    structures to process   (default: $INPUTS from config.sh)
#   -l, --ligand FILE   substrate SDF           (default: $LIGAND from config.sh)
#   -e, --env NAME      conda env               (default: $CONDA_ENV)
#   -r, --references DIR  structures added to every run (default: $REFERENCES)
#       --no-references   do not add them
#   -t, --tag NAME      job-name prefix, for running sets in parallel
#   -n, --limit N       only the first N structures (references still added)
#   -y, --yes           skip the confirmation prompt
#   -h, --help          show this
#
# Examples:
#   ./submit_all.sh
#   ./submit_all.sh 10
#   ./submit_all.sh -w /scratch/me/run1 -i /scratch/me/designs 10
#
# A limited run gets its own subdirectory (<work>/testN) so its outputs never
# mix with, or get overwritten by, the full run.
set -eu
cd "$(dirname "$0")"

# `bsub < script` feeds the script to LSF on stdin, so inside the job $0 is a
# spool file, not this directory — dirname "$0" is useless there. The absolute
# path is baked into each script at submit time instead (see submit() below).
HPC_DIR=$(pwd)

# LSF MAX_JOB_ARRAY_SIZE. Arrays larger than this are rejected outright.
ARRAY_MAX="${ARRAY_MAX:-1000}"

usage() { sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'; }

LIMIT=""
ASSUME_YES=""
NO_REFS=""
TAGNAME=""
_work=""; _inputs=""; _ligand=""; _env=""; _refs=""

while [ $# -gt 0 ]; do
    case "$1" in
        -w|--work)    _work="${2:?--work needs a directory}";   shift 2 ;;
        -i|--inputs)  _inputs="${2:?--inputs needs a directory}"; shift 2 ;;
        -l|--ligand)  _ligand="${2:?--ligand needs a file}";     shift 2 ;;
        -e|--env)     _env="${2:?--env needs a name}";           shift 2 ;;
        -r|--references) _refs="${2:?--references needs a directory}"; shift 2 ;;
        --no-references) NO_REFS=1; shift ;;
        -t|--tag)     TAGNAME="${2:?--tag needs a name}";        shift 2 ;;
        -n|--limit)   LIMIT="${2:?--limit needs a number}";      shift 2 ;;
        -y|--yes)     ASSUME_YES=1; shift ;;
        -h|--help)    usage; exit 0 ;;
        -*)           echo "Unknown option: $1" >&2; usage >&2; exit 1 ;;
        *)            LIMIT="$1"; shift ;;
    esac
done

if [ -n "$LIMIT" ]; then
    case "$LIMIT" in
        ''|*[!0-9]*) echo "Limit must be a number, got: $LIMIT" >&2; exit 1 ;;
    esac
fi

# Flags win over the environment, which wins over config.sh's defaults. Setting
# these before sourcing works because every value there uses ${VAR:-default}.
[ -n "$_work" ]   && WORK="$_work"
[ -n "$_inputs" ] && INPUTS="$_inputs"
[ -n "$_ligand" ] && LIGAND="$_ligand"
[ -n "$_env" ]    && CONDA_ENV="$_env"
[ -n "$_refs" ]   && REFERENCES="$_refs"
[ -n "$NO_REFS" ] && REFERENCES=""

. ./config.sh

# Isolate a limited run in its own subdirectory.
[ -n "$LIMIT" ] && WORK="$WORK/test$LIMIT"

if [ ! -d "$INPUTS" ]; then
    echo "Input directory does not exist: $INPUTS" >&2
    echo "Set it with --inputs DIR" >&2
    exit 1
fi

# Everything below is written into runconfig.sh and read by jobs whose working
# directory is not this one, so relative paths must be resolved here or they
# will not resolve there.
mkdir -p "$WORK"
WORK=$(cd "$WORK" && pwd)
INPUTS=$(cd "$INPUTS" && pwd)
PDB_INPUTS="$WORK/pdb_inputs"          # re-derived from the absolute WORK
case "$LIGAND" in
    /*) ;;
    *)  LIGAND="$(cd "$(dirname "$LIGAND")" && pwd)/$(basename "$LIGAND")" ;;
esac

if [ ! -f "$LIGAND" ]; then
    echo "Ligand file not found: $LIGAND" >&2
    echo "Set it with --ligand FILE" >&2
    exit 1
fi

# Every Stage A task needs fpocket. It is not vendored here -- it is MIT but
# platform-specific, and a committed binary is neither reproducible nor allowed.
if ! command -v fpocket >/dev/null 2>&1; then
    echo "ERROR: fpocket is not on PATH." >&2
    echo "Install it into the env:  conda install -c bioconda fpocket -y" >&2
    echo "or create the env:        conda env create -f envs/docking.yml" >&2
    exit 1
fi

mkdir -p logs "$WORK" "$WORK/shards" "$WORK/docking_out" "$WORK/results"

# preflight_inputs.py drops anything the pipeline would silently FAIL on — above
# all, structures with no heme iron, which the whole pipeline is anchored to.
# Takes seconds and needs no env, so it is never worth skipping.
python3 preflight_inputs.py "$INPUTS" \
    --manifest "$WORK/manifest.txt" \
    --report   "$WORK/preflight_report.tsv"

if [ -n "$LIMIT" ]; then
    head -n "$LIMIT" "$WORK/manifest.txt" > "$WORK/manifest.tmp"
    mv "$WORK/manifest.tmp" "$WORK/manifest.txt"
    echo
    echo "TEST RUN — limited to $LIMIT structure(s), isolated in:"
    echo "  $WORK"
fi

# Reference structures are appended AFTER the limit, so a --limit 10 run is
# 10 designs PLUS the references rather than 10 total. Without this a limited
# run would contain no references at all (they sort after the rfd3_* designs)
# and the comparison the clustering exists to make would be impossible.
N_REFS=0
if [ -n "$REFERENCES" ] && [ -d "$REFERENCES" ]; then
    REFERENCES=$(cd "$REFERENCES" && pwd)
    for r in "$REFERENCES"/*.pdb "$REFERENCES"/*.cif; do
        [ -f "$r" ] || continue
        # Skip if this path is already in the manifest (references inside INPUTS).
        if ! grep -Fxq "$r" "$WORK/manifest.txt"; then
            echo "$r" >> "$WORK/manifest.txt"
            N_REFS=$((N_REFS + 1))
        fi
    done
    [ "$N_REFS" -gt 0 ] && echo "Added $N_REFS reference structure(s) from $REFERENCES"
fi

N=$(wc -l < "$WORK/manifest.txt" | tr -d ' ')
if [ "$N" -eq 0 ]; then
    echo "No usable structures — nothing to submit." >&2
    exit 1
fi

# Asking for more clusters than you have structures produces singletons and an
# unreadable figure. Keep at least ~3 structures per cluster.
MAX_SENSIBLE=$(( N / 3 ))
[ "$MAX_SENSIBLE" -lt 2 ] && MAX_SENSIBLE=2
if [ "$N_CLUSTERS" -gt "$MAX_SENSIBLE" ]; then
    echo "Note: N_CLUSTERS=$N_CLUSTERS is too many for $N structure(s) — using $MAX_SENSIBLE."
    N_CLUSTERS="$MAX_SENSIBLE"
fi

# Job names must be unique per concurrent run, or the -w dependencies would
# latch onto the wrong jobs — two design sets submitted as "cdfull" would each
# satisfy the other's dependencies. Use --tag when running sets side by side.
TAG="cd${TAGNAME:-}${LIMIT:-full}"

echo
echo "  structures    : $N"
echo "  inputs        : $INPUTS"
[ "$N_REFS" -gt 0 ] && echo "  references    : $N_REFS from $REFERENCES"
echo "  work dir      : $WORK"
echo "  job prefix    : $TAG"
echo "  conda env     : $CONDA_ENV"
echo "  ligand        : $LIGAND"
echo "  concurrent    : $MAXPAR"
echo "  exhaustiveness: $EXHAUSTIVENESS"
echo "  clusters      : $N_CLUSTERS"
if [ -z "$ASSUME_YES" ]; then
    printf '\nSubmit? [y/N] '
    read -r reply
    case "$reply" in
        [yY]*) ;;
        *) echo "Aborted."; exit 0 ;;
    esac
fi

# This LSF does not propagate the submitting environment to jobs, so every
# resolved setting is written here and sourced by absolute path instead.
RUNCONFIG="$WORK/runconfig.sh"
cat > "$RUNCONFIG" <<EOF
# Generated by submit_all.sh on $(date). Do not edit — regenerated each submit.
TEAM="$TEAM"
PROJECT="$PROJECT"
WORK="$WORK"
INPUTS="$INPUTS"
PDB_INPUTS="$PDB_INPUTS"
LIGAND="$LIGAND"
REFERENCES="$REFERENCES"
CONDA_BASE="$CONDA_BASE"
CONDA_ENV="$CONDA_ENV"
MAXPAR="$MAXPAR"
N_CLUSTERS="$N_CLUSTERS"
EXHAUSTIVENESS="$EXHAUSTIVENESS"
. "$HPC_DIR/config.sh"
EOF
echo "Run config: $RUNCONFIG"

# bsub reads the script from stdin, so substitute the runconfig path into it on
# the way through. The spool copy LSF creates then carries the absolute path.
submit() {
    _script="$1"; _offset="$2"; shift 2
    sed -e "s|__RUNCONFIG__|$RUNCONFIG|g" \
        -e "s|__OFFSET__|$_offset|g" "$_script" | bsub "$@"
}

# Submit one stage as however many arrays the LSF cap requires, and echo the
# dependency expression that waits for all of them.
submit_chunked() {
    _script="$1"; _prefix="$2"; _wait="$3"
    _start=0; _i=0; _dep=""
    while [ "$_start" -lt "$N" ]; do
        _rem=$((N - _start))
        _size=$ARRAY_MAX
        [ "$_rem" -lt "$ARRAY_MAX" ] && _size=$_rem
        _jn="${_prefix}${_i}"
        if [ -n "$_wait" ]; then
            submit "$_script" "$_start" -J "${_jn}[1-${_size}]%$MAXPAR" -w "$_wait" >&2
        else
            submit "$_script" "$_start" -J "${_jn}[1-${_size}]%$MAXPAR" >&2
        fi
        _dep="${_dep:+$_dep && }ended($_jn)"
        _start=$((_start + _size)); _i=$((_i + 1))
    done
    printf '%s' "$_dep"
}

# ended() not done(): done() on an array requires EVERY element to succeed, so a
# single transient failure (a flaky conda activation, a node hiccup) among 229
# tasks would leave the collect job pending forever and block clustering. The
# collect scripts already validate their inputs and exit non-zero if there is
# genuinely nothing to work with, so partial failure is handled there.
# The collect jobs themselves stay on done(), since if a collect fails the next
# stage really must not run.
DEP_A=$(submit_chunked 10_stageA.sh "${TAG}A" "")
submit 20_collectA.sh 0 -J "${TAG}Ac" -w "$DEP_A"

DEP_B=$(submit_chunked 30_stageB.sh "${TAG}B" "done(${TAG}Ac)")
submit 40_collectB.sh 0 -J "${TAG}Bc" -w "$DEP_B"

echo
echo "Submitted as ${TAG}A* / ${TAG}Ac / ${TAG}B* / ${TAG}Bc"
echo "Watch:  bjobs -A        Logs:  $(pwd)/logs/"
