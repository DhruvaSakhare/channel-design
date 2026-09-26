#!/usr/bin/env bash
# Does this checkout work?
#
# Two tiers, so it says something useful whatever you have installed:
#
#   Tier 1  always runs. Pure Python, no GPU, no cluster, no external tools,
#           no network. This is what CI runs and what a reviewer can run.
#   Tier 2  runs only if fpocket, Java and CAVER are present: the real channel
#           pipeline over the three bundled reference crystals. Skipped, not
#           failed, when the tools are missing -- CAVER is GPLv3 and fetched
#           separately, so not having it is the normal state of a fresh clone.
#
# The GPU stages (Boltz-2, RFdiffusion3, LigandMPNN, RF3) are deliberately not
# exercised here. See envs/design.md.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
export MPLBACKEND=Agg

rule() { printf '\n──────── %s ────────\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

rule "TIER 1 — test suite"
if ! have python3; then
    echo "FAIL: no python3 on PATH" >&2
    exit 1
fi
if ! python3 -c "import pytest" 2>/dev/null; then
    echo "SKIP: pytest not installed."
    echo "      pip install pytest pyyaml numpy matplotlib"
else
    python3 -m pytest tests/ -q || { echo "FAIL: test suite" >&2; exit 1; }
fi

rule "TIER 1 — resolved configuration"
python3 enzyme_design/partial_diffusion/site.py
python3 enzyme_design/lib/paths.py

rule "TIER 2 — external tools"
CAVER_DIR="${CAVER_HOME:-$REPO_ROOT/third_party/caver}"
missing=""
have fpocket || missing="$missing fpocket"
have java    || missing="$missing java"
[ -f "$CAVER_DIR/caver.jar" ] || missing="$missing caver"

if [ -n "$missing" ]; then
    cat <<TXT
SKIP: missing:$missing

  Tier 1 passed, which is the part that does not depend on external software.
  To run the real channel pipeline as well:

      conda env create -f envs/docking.yml
      conda activate channel-design-docking
      ./scripts/fetch_third_party.sh

TXT
    echo "Smoke test: TIER 1 PASSED, TIER 2 SKIPPED."
    exit 0
fi

echo "fpocket: $(command -v fpocket)"
echo "java:    $(java -version 2>&1 | head -1)"
echo "caver:   $CAVER_DIR/caver.jar"

SMOKE="${SMOKE_DIR:-$REPO_ROOT/work/smoketest}"
rm -rf "$SMOKE"; mkdir -p "$SMOKE/inputs"
cp channel_discovery/fpocket_pipeline/inputs/*.pdb "$SMOKE/inputs/"
echo "Structures: $(ls "$SMOKE/inputs" | tr '\n' ' ')"

rule "TIER 2 — Stage A (pockets)"
( cd channel_discovery/fpocket_pipeline && \
  python3 pipeline.py "$SMOKE/inputs" --skip-docking \
      --outputs-dir "$SMOKE/outputs" ) || {
    echo "FAIL: stage A" >&2; exit 1; }

TSV="$SMOKE/outputs/pocket_selection.tsv"
[ -f "$TSV" ] || { echo "FAIL: no pocket_selection.tsv" >&2; exit 1; }
passed=$(awk -F'\t' 'NR>1 && $2=="PASS"' "$TSV" | wc -l | tr -d ' ')
echo "Stage A: $passed / 3 PASS"
[ "$passed" -gt 0 ] || { echo "FAIL: nothing passed the pocket filter" >&2; exit 1; }

rule "TIER 2 — Stage B (tunnels)"
( cd channel_discovery/caver_pipeline && \
  python3 python_scripts/run_batch.py \
      --pdb-dir "$SMOKE/inputs" --results-dir "$SMOKE/results" \
      --fpocket-dir "$SMOKE/outputs" && \
  python3 python_scripts/cluster_tunnels.py \
      --results-dir "$SMOKE/results" --fpocket-dir "$SMOKE/outputs" \
      --out "$SMOKE/results/clustering" ) || {
    echo "FAIL: stage B" >&2; exit 1; }

rule "TIER 2 — checks"
ok=1
for f in "$SMOKE/outputs/pocket_selection.tsv" \
         "$SMOKE/results/clustering/cluster_assignments.csv"; do
    if [ -f "$f" ]; then echo "  OK      $(basename "$f")"
    else echo "  MISSING $(basename "$f")"; ok=0; fi
done
[ "$ok" -eq 1 ] || { echo "FAIL: expected outputs missing" >&2; exit 1; }

echo
echo "Smoke test: TIER 1 AND TIER 2 PASSED."
echo "Results in $SMOKE"
