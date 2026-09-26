#!/bin/sh
# STAGE B (array): CAVER tunnel detection, one structure per task.
# CAVER is a single JVM capped at -Xmx1200m (hardcoded in run_batch.py), so one
# core and modest memory is right. Raise both together if you hit OOM on large
# receptors — the -Xmx is at caver_pipeline/python_scripts/run_batch.py:218.
#BSUB -q hpc
#BSUB -n 1
#BSUB -R "rusage[mem=4GB]"
# DTU's esub rejects a -M more than 1GB above rusage[mem]. Keep them in step.
#BSUB -M 5GB
#BSUB -W 02:00
#BSUB -o logs/stageB_%J_%I.out
#BSUB -e logs/stageB_%J_%I.err
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

# CAVER needs PDB; 20_collectA.sh converted any CIF inputs into $PDB_INPUTS.
PDB="$PDB_INPUTS/$STEM.pdb"
if [ ! -f "$PDB" ]; then
    echo "[task ${IDX}] $STEM — no converted PDB at $PDB, skipping" >&2
    exit 0
fi

# run_batch.py would skip non-PASS structures itself, but exiting here avoids
# spinning up a JVM just to no-op.
if ! awk -F'\t' -v s="$STEM" 'NR>1 && $1==s && $2=="PASS" { found=1 } END { exit !found }' \
        "$WORK/outputs/pocket_selection.tsv"; then
    echo "[task ${IDX}] $STEM — not PASS in Stage A, skipping"
    exit 0
fi

echo "[task ${IDX}] $STEM"

# Shared --results-dir is fine: per-structure output lands in results/<stem>/,
# which never collides. The combined results/tunnel_selection.csv DOES race
# between tasks, so 40_collectB.sh rebuilds it from scratch afterwards.
# --skip-existing makes re-runs incremental: a structure that already has
# results/<stem>/out/summary.txt is left alone, so adding new enzymes to the
# input folder only costs CAVER time for the new ones. Without it, every
# resubmit recomputes all 229.
cd "$PROJECT/caver_pipeline"
python3 python_scripts/run_batch.py \
    --pdb "$PDB" \
    --results-dir "$WORK/results" \
    --fpocket-dir "$WORK/outputs" \
    --skip-existing
