#!/bin/sh
# Rebuild the combined tunnel table, then cluster across all structures.
# Clustering is inherently a gather step — it compares every structure against
# every other — so it cannot be part of the array.
#BSUB -q hpc
#BSUB -n 4
#BSUB -R "span[hosts=1]"
#BSUB -R "rusage[mem=8GB]"
# DTU's esub rejects a -M more than 1GB above rusage[mem]. Keep them in step.
#BSUB -M 9GB
#BSUB -W 02:00
#BSUB -o logs/collectB_%J.out
#BSUB -e logs/collectB_%J.err
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

cd "$PROJECT/caver_pipeline"

# --skip-existing recomputes nothing: every structure already has
# results/<stem>/out/summary.txt from the array, so this only re-emits the rows
# into one complete tunnel_selection.csv, repairing the races from Stage B.
python3 python_scripts/run_batch.py \
    --pdb-dir "$PDB_INPUTS" \
    --results-dir "$WORK/results" \
    --fpocket-dir "$WORK/outputs" \
    --skip-existing

python3 python_scripts/cluster_tunnels.py \
    --results-dir "$WORK/results" \
    --fpocket-dir "$WORK/outputs" \
    --n-clusters "$N_CLUSTERS" \
    --out "$WORK/results/clustering"

echo
echo "Done. Key outputs:"
echo "  $WORK/outputs/pocket_selection.tsv"
echo "  $WORK/results/tunnel_selection.csv"
echo "  $WORK/results/clustering/cluster_assignments.csv"
