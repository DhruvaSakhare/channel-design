#!/bin/sh
# STAGE A (array): fpocket + filter + dock + pose analysis, one structure per task.
# Submitted by submit_all.sh, which supplies -J with the right array range.
#BSUB -q hpc
#BSUB -n 4
#BSUB -R "span[hosts=1]"
#BSUB -R "rusage[mem=4GB]"
# DTU's esub rejects a -M more than 1GB above rusage[mem]. Keep them in step.
#BSUB -M 5GB
#BSUB -W 04:00
#BSUB -o logs/stageA_%J_%I.out
#BSUB -e logs/stageA_%J_%I.err
set -eu
# This LSF does not propagate the submitting environment, and `bsub < script`
# makes $0 a spool file, so neither env vars nor $0 can locate our settings.
# submit_all.sh substitutes the absolute path to a generated runconfig below
# before piping the script to bsub. The fallback lets the script still run
# standalone (e.g. by hand on an interactive node).
RUNCONFIG="__RUNCONFIG__"
# Pattern deliberately omits the leading underscores so the sed substitution
# cannot rewrite it too — otherwise the fallback would clobber the real path.
case "$RUNCONFIG" in
    *RUNCONFIG__) RUNCONFIG="$(cd "$(dirname "$0")" && pwd)/config.sh" ;;
esac
. "$RUNCONFIG"
activate_env

# LSF caps job arrays (MAX_JOB_ARRAY_SIZE, 1000 here), so large runs are split
# into several arrays. Each gets an index offset substituted in at submit time;
# LSB_JOBINDEX is always 1..size, so the offset maps it back to a manifest line.
OFFSET="__OFFSET__"
case "$OFFSET" in *OFFSET__) OFFSET=0 ;; esac
IDX=$((LSB_JOBINDEX + OFFSET))
STRUCT=$(sed -n "${IDX}p" "$WORK/manifest.txt")
STEM=$(stem_of "$STRUCT")
echo "[task ${IDX}] $STEM"

# Each task gets its OWN outputs dir. This is not optional: pipeline.py
# enumerates every structure in --outputs-dir and rewrites pocket_selection.tsv
# from that view, so tasks sharing one dir would race and clobber the table.
# 20_collectA.sh merges the shards afterwards.
SHARD="$WORK/shards/$STEM"
mkdir -p "$SHARD/in"
cp "$STRUCT" "$SHARD/in/"

# Constrain Vina to our actual LSF allocation. Without this it uses cpu=0,
# meaning every core on the physical node — see docking.py.
export VINA_CPU="${LSB_DJOB_NUMPROC:-4}"
export VINA_SEED=42          # reproducible poses; drop for independent replicates
export OMP_NUM_THREADS="$VINA_CPU"

# docking_out filenames embed stem + box coords, so tasks can share it safely.
cd "$PROJECT/fpocket_pipeline"
python3 pipeline.py "$SHARD/in" \
    -l "$LIGAND" \
    --prepare \
    --outputs-dir "$SHARD/out" \
    --docking-out "$WORK/docking_out" \
    --exhaustiveness "$EXHAUSTIVENESS"
