#!/bin/sh
# Merge the Stage A shards into the single outputs/ layout Stage B expects:
#   outputs/pocket_selection.tsv        <- run_batch.py load_pocket_selection()
#   outputs/<stem>_out/pockets/*.pqr    <- run_batch.py pocket_center()
# Both must sit in the SAME directory, which is what --fpocket-dir points at.
#BSUB -q hpc
#BSUB -n 1
#BSUB -R "rusage[mem=2GB]"
#BSUB -W 00:30
#BSUB -o logs/collectA_%J.out
#BSUB -e logs/collectA_%J.err
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

mkdir -p "$WORK/outputs"

# fpocket _out/ dirs are named per structure and never collide.
# MOVE rather than copy: copying leaves a second full set under shards/, which
# at ~1400 structures is tens of GB of pure duplication and will exhaust a
# /work3 quota. Stage A is re-runnable if a shard is ever needed again.
n=0
for d in "$WORK"/shards/*/out; do
    [ -d "$d" ] || continue
    for o in "$d"/*_out; do
        [ -d "$o" ] || continue
        rm -rf "$WORK/outputs/$(basename "$o")"
        mv "$o" "$WORK/outputs/"
        n=$((n + 1))
    done
done
echo "collected $n fpocket output dir(s)"

# Drop fpocket's visualisation output. Downstream only ever reads:
#   <stem>_info.txt              filter_pockets.py metrics
#   pockets/pocket<N>_vert.pqr   run_batch.py pocket_center()
#   <stem>_out.pdb               pipeline.py find_receptor_pdb() fallback
# The .tcl/.pml/VMD/PYMOL scripts and per-pocket _atm.pdb files are for manual
# inspection only and dominate the on-disk size.
if [ "${PRUNE_FPOCKET:-1}" = "1" ]; then
    before=$(du -sm "$WORK/outputs" 2>/dev/null | cut -f1)
    find "$WORK/outputs" -type f \( -name '*.tcl' -o -name '*.pml' \
        -o -name '*_VMD.sh' -o -name '*_PYMOL.sh' -o -name '*_pockets.pqr' \
        -o -name 'pocket*_atm.pdb' \) -delete 2>/dev/null || true
    after=$(du -sm "$WORK/outputs" 2>/dev/null | cut -f1)
    echo "pruned fpocket visualisation files: ${before}MB -> ${after}MB"
fi

# Concatenate the per-shard tables, keeping exactly one header line.
awk 'FNR==1 { if (seen++) next } { print }' \
    "$WORK"/shards/*/out/pocket_selection.tsv \
    > "$WORK/outputs/pocket_selection.tsv"

total=$(($(wc -l < "$WORK/outputs/pocket_selection.tsv") - 1))
passed=$(awk -F'\t' 'NR>1 && $2=="PASS"' "$WORK/outputs/pocket_selection.tsv" | wc -l)
echo "pocket_selection.tsv: $total structure(s), $passed PASS"

if [ "$passed" -eq 0 ]; then
    echo "ERROR: nothing passed the pocket filter — Stage B would do nothing." >&2
    echo "Check the filter thresholds (--druggability/--volume/--fe-proximity)." >&2
    exit 1
fi

# ── prepare CAVER inputs ──────────────────────────────────────────────────────
# run_batch.py globs *.pdb only, so CIF inputs must be converted first. Doing it
# here (single job) rather than per-array-task avoids tasks racing on the same
# output directory.
#
# Driven by the manifest, NOT by globbing $INPUTS: reference structures live in
# their own directory and would otherwise never reach $PDB_INPUTS, so Stage B
# would skip them and they would be missing from the clustering — which is the
# one comparison they exist to provide.
mkdir -p "$PDB_INPUTS"
n_conv=0; n_copy=0; n_skip=0

while IFS= read -r src; do
    [ -f "$src" ] || continue
    stem=$(stem_of "$src")
    dest="$PDB_INPUTS/$stem.pdb"
    if [ -f "$dest" ]; then
        n_skip=$((n_skip + 1))
        continue
    fi
    case "$src" in
        *.cif)
            if python3 "$PROJECT/caver_pipeline/python_scripts/cif_to_pdb.py" \
                    "$src" -o "$dest" >/dev/null; then
                n_conv=$((n_conv + 1))
            else
                echo "  WARN: CIF conversion failed for $stem" >&2
            fi
            ;;
        *.pdb)
            cp "$src" "$dest" && n_copy=$((n_copy + 1))
            ;;
    esac
done < "$WORK/manifest.txt"

echo "CAVER inputs: $n_conv converted, $n_copy copied, $n_skip already present"

n_pdb=$(find "$PDB_INPUTS" -maxdepth 1 -name '*.pdb' | wc -l | tr -d ' ')
echo "CAVER inputs ready: $n_pdb PDB file(s) in $PDB_INPUTS"
if [ "$n_pdb" -eq 0 ]; then
    echo "ERROR: no PDB files for CAVER — CIF conversion produced nothing." >&2
    exit 1
fi
