#!/bin/sh
# Smoke test: run the 3 bundled structures end to end, in an INTERACTIVE session,
# before committing an array job. Catches env and path problems in ~minutes
# instead of after 300 queued tasks fail identically.
#
# Get a session first (do NOT run this on a login node):
#   bsub -Is -q hpc -W 1:00 -n 4 -R "rusage[mem=4GB]" -R "span[hosts=1]" bash
# then:
#   cd ~/channel_discovery/hpc && ./05_smoketest.sh
set -eu
cd "$(dirname "$0")"
. ./config.sh
activate_env

SMOKE="$WORK/smoketest"
rm -rf "$SMOKE"
mkdir -p "$SMOKE/inputs"
cp "$PROJECT/fpocket_pipeline/inputs/"*.pdb "$SMOKE/inputs/"
echo "Structures: $(ls "$SMOKE/inputs" | tr '\n' ' ')"

export VINA_CPU="${LSB_DJOB_NUMPROC:-4}"
export VINA_SEED=42
export MPLBACKEND=Agg

echo
echo "──────── STAGE A ────────"
cd "$PROJECT/fpocket_pipeline"
python3 pipeline.py "$SMOKE/inputs" \
    -l "$LIGAND" \
    --prepare \
    --outputs-dir "$SMOKE/outputs" \
    --docking-out "$SMOKE/docking_out"

TSV="$SMOKE/outputs/pocket_selection.tsv"
[ -f "$TSV" ] || { echo "FAIL: no pocket_selection.tsv written" >&2; exit 1; }
passed=$(awk -F'\t' 'NR>1 && $2=="PASS"' "$TSV" | wc -l | tr -d ' ')
echo
echo "Stage A: $passed / 3 PASS"
[ "$passed" -gt 0 ] || { echo "FAIL: nothing passed the pocket filter" >&2; exit 1; }

echo
echo "──────── STAGE B ────────"
cd "$PROJECT/caver_pipeline"
python3 python_scripts/run_batch.py \
    --pdb-dir "$SMOKE/inputs" \
    --results-dir "$SMOKE/results" \
    --fpocket-dir "$SMOKE/outputs"

python3 python_scripts/cluster_tunnels.py \
    --results-dir "$SMOKE/results" \
    --fpocket-dir "$SMOKE/outputs" \
    --out "$SMOKE/results/clustering"

echo
echo "──────── CHECKS ────────"
for f in "$SMOKE/outputs/pocket_selection.tsv" \
         "$SMOKE/results/tunnel_selection.csv" \
         "$SMOKE/results/clustering/cluster_assignments.csv"; do
    [ -f "$f" ] && echo "  OK    $f" || { echo "  FAIL  missing: $f"; exit 1; }
done

# Worth eyeballing: with probe_radius 0.4 and no minimum-bottleneck filter,
# confirm the tunnels being clustered are actually wide enough to matter.
echo
echo "Bottleneck radii of the tunnels that were kept (Å):"
awk -F',' 'NR==1 { for(i=1;i<=NF;i++){ if($i ~ /bottleneck/) b=i; if($i ~ /stem/) s=i } next }
           b { print "  " $s "  " $b }' "$SMOKE/results/tunnel_selection.csv" | head -20

echo
echo "Smoke test passed. Scale up with ./submit_all.sh"
