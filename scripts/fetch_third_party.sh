#!/usr/bin/env bash
# Download the third-party tools this project uses but does not redistribute.
#
# CAVER 3.0 is GPLv3 and is deliberately not vendored here: shipping the jars
# would put this repository's own Apache-2.0 code next to copyleft binaries,
# and iGEM asks that source produce the output rather than committed binaries.
#
#   ./scripts/fetch_third_party.sh
#
# Already have CAVER? Skip this and point the pipeline at it instead:
#   export CAVER_HOME=/opt/caver-3.0.3
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${CAVER_HOME:-$REPO_ROOT/third_party/caver}"
CAVER_URL="${CAVER_URL:-https://www.caver.cz/}"

say() { printf '\n== %s\n' "$*"; }

say "CAVER 3.0 -> $DEST"
if [ -f "$DEST/caver.jar" ]; then
    echo "   already present, nothing to do."
else
    cat <<TXT
   CAVER is distributed from caver.cz behind a registration form, so it cannot
   be fetched non-interactively. Download "CAVER 3.0 command line" from:

       $CAVER_URL

   then unpack it so that this path exists:

       $DEST/caver.jar
       $DEST/lib/

   and re-run this script to verify.

   CAVER 3.0 is GPLv3 (Masaryk University). If you publish results made with
   it, cite: Chovancova E. et al. (2012) CAVER 3.0: A Tool for the Analysis of
   Transport Pathways in Dynamic Protein Structures. PLoS Comput Biol
   8(10):e1002708.
TXT
fi

say "fpocket"
if command -v fpocket >/dev/null 2>&1; then
    echo "   found: $(command -v fpocket)"
else
    echo "   not on PATH. Install it with:  conda install -c bioconda fpocket -y"
    echo "   (it is also in envs/docking.yml)"
fi

say "Java (CAVER needs 8)"
if command -v java >/dev/null 2>&1; then
    java -version 2>&1 | head -1 | sed 's/^/   /'
else
    echo "   not on PATH. envs/docking.yml pins openjdk=8."
fi

say "Summary"
if [ -f "$DEST/caver.jar" ] && command -v fpocket >/dev/null 2>&1 \
   && command -v java >/dev/null 2>&1; then
    echo "   All three present. The channel pipeline can run."
else
    echo "   Some pieces are missing (see above). The pocket stage still runs"
    echo "   without CAVER, and --skip-docking runs without vina."
    exit 1
fi
