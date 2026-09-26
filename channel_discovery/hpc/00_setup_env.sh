#!/bin/sh
# Run ONCE, on a LOGIN node (not via bsub). Builds the conda env, then verifies
# the fragile parts before you spend any queue time.
#
# This follows your proven bio_docking recipe exactly — conda-forge swig +
# boost-cpp, "numpy<2.0" installed FIRST, and BOOST_INCLUDE/BOOST_LIB exported
# so that `pip install vina==1.2.7` can build its bindings. Two additions:
#   - matplotlib, which bio_docking does not have but the whole caver stage
#     needs (extract_tunnel_R.py imports pyplot at module level)
#   - fpocket + openjdk, which the channel pipeline needs and docking did not
set -eu
cd "$(dirname "$0")"
. ./config.sh

CONDA_ROOT=$(find_conda_base) || {
    echo "ERROR: cannot find a conda installation." >&2
    echo "  Looked on PATH and in the usual roots. Find yours with:" >&2
    echo "    ls -d \$HOME/mini* \$HOME/anaconda3 /work3/\$USER/mini* 2>/dev/null" >&2
    echo "  then set CONDA_BASE in config.sh." >&2
    exit 1
}
echo "Using conda at: $CONDA_ROOT"
# shellcheck disable=SC1091
. "$CONDA_ROOT/etc/profile.d/conda.sh"

if conda env list | grep -q "^${CONDA_ENV} "; then
    echo "Env ${CONDA_ENV} already exists — skipping create. Delete it first to rebuild."
else
    conda create -n "$CONDA_ENV" python=3.12 -y
fi
conda activate "$CONDA_ENV"

# Build deps for vina, plus the two non-Python tools this pipeline shells out to.
# openjdk=8: CAVER 3.0 is from 2013 and is happiest on Java 8.
conda install -c conda-forge swig boost-cpp openjdk=8 -y
conda install -c bioconda fpocket -y

# numpy first and pinned <2.0 — installing it after rdkit/vina pulls numpy 2.x
# and breaks the ABI they were built against.
pip install "numpy<2.0"

export BOOST_INCLUDE="$CONDA_PREFIX/include"
export BOOST_LIB="$CONDA_PREFIX/lib"

pip install \
  vina==1.2.7 \
  meeko==0.7.1 \
  rdkit==2025.9.5 \
  scipy==1.16.1 \
  matplotlib

echo
echo "=== verifying the parts that usually break ==="
python3 - <<'PY'
import sys
ok = True

def check(label, fn):
    global ok
    try:
        print(f"  OK    {label}: {fn()}")
    except Exception as e:
        ok = False
        print(f"  FAIL  {label}: {type(e).__name__}: {e}")

check("vina bindings", lambda: __import__("vina").__version__)
check("rdkit",         lambda: __import__("rdkit").__version__)
check("meeko",         lambda: __import__("meeko").__version__)
check("numpy",         lambda: __import__("numpy").__version__)
check("scipy",         lambda: __import__("scipy").__version__)
check("matplotlib",    lambda: __import__("matplotlib").__version__)

import numpy
if numpy.__version__.startswith("2."):
    ok = False
    print("  FAIL  numpy is 2.x — rdkit/vina wheels expect 1.x. Reinstall with 'numpy<2.0'.")

# The exact deprecated call path docking.py depends on. Present in meeko 0.7.1,
# gone in whatever comes next — this is why the version is pinned.
try:
    from meeko import MoleculePreparation
    assert hasattr(MoleculePreparation, "write_pdbqt_string")
    print("  OK    meeko legacy write_pdbqt_string() present")
except Exception as e:
    ok = False
    print(f"  FAIL  meeko legacy API missing: {e}")

sys.exit(0 if ok else 1)
PY

echo
command -v fpocket >/dev/null && echo "  OK    fpocket: $(command -v fpocket)" \
                              || echo "  FAIL  fpocket not on PATH"
java -version 2>&1 | head -1 | sed 's/^/  OK    java: /'

echo
echo "Ready. Put your receptor .pdb files in $INPUTS, then run ./submit_all.sh"
