#!/usr/bin/env bash
# Generate a dependency lockfile from the environment that is active RIGHT NOW.
#
# Run this on the machine where the environment actually works, with that
# environment activated. That is the entire point: a lock records what a
# working install contains. Generated anywhere else it is fiction.
#
#   conda activate bio_docking
#   ./scripts/make_lockfiles.sh docking
#
#   conda activate channel-design-boltz
#   ./scripts/make_lockfiles.sh boltz
#
# Writes envs/requirements-<name>.lock.txt, and, inside a conda env, also
# envs/<name>.conda-explicit.txt -- both are needed, because pip freeze cannot
# see conda-installed packages like fpocket or openjdk.
set -euo pipefail

NAME="${1:-}"
if [ -z "$NAME" ]; then
    echo "usage: $0 <name>        e.g. docking | boltz" >&2
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if ! command -v pip >/dev/null 2>&1; then
    echo "ERROR: no pip on PATH. Activate the environment first." >&2
    exit 1
fi

STAMP="# generated $(date -u +%Y-%m-%dT%H:%MZ) on $(uname -s)-$(uname -m)"
PYVER="# python $(python3 -V 2>&1 | cut -d' ' -f2)"
ENVNAME="# conda env: ${CONDA_DEFAULT_ENV:-<not a conda env>}"

# --- sanity: is this plausibly the right environment? ----------------------
case "$NAME" in
  docking)
    python3 - <<'PY' || { echo "WARNING: this does not look like the docking env." >&2; }
import importlib, sys
missing = [m for m in ("numpy", "rdkit", "vina", "meeko")
           if importlib.util.find_spec(m) is None]
sys.exit(1 if missing else 0)
PY
    ;;
  boltz)
    python3 -c "import importlib,sys; sys.exit(0 if importlib.util.find_spec('boltz') else 1)" \
      || echo "WARNING: boltz is not importable in this environment." >&2
    ;;
esac

# --- pip side ---------------------------------------------------------------
OUT="envs/requirements-${NAME}.lock.txt"
{
    echo "# Full dependency lock for the '${NAME}' environment."
    echo "$STAMP"
    echo "$PYVER"
    echo "$ENVNAME"
    echo "#"
    echo "# Reproduce with:  pip install -r ${OUT}"
    echo "# Regenerate with: ./scripts/make_lockfiles.sh ${NAME}"
    echo "#"
    echo "# NOTE: pip cannot see conda-installed packages. If this environment"
    echo "# was built with conda, the file beside this one is also required."
    echo
    pip freeze
} > "$OUT"
echo "wrote $OUT  ($(grep -cv '^#' "$OUT" | tr -d ' ') pinned packages)"

# --- conda side -------------------------------------------------------------
if [ -n "${CONDA_DEFAULT_ENV:-}" ] && command -v conda >/dev/null 2>&1; then
    COUT="envs/${NAME}.conda-explicit.txt"
    conda list --explicit > "$COUT"
    echo "wrote $COUT  (recreate with: conda create --name <env> --file $COUT)"
else
    echo "note: not inside a conda env, so no conda-explicit file was written."
fi

echo
echo "Now commit them:"
echo "    git add envs/"
echo "    git commit -m 'Add verified dependency locks for ${NAME}'"
