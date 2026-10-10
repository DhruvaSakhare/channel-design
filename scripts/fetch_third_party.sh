#!/usr/bin/env bash
# Install the two external tools this project needs but does not redistribute.
#
#   ./scripts/fetch_third_party.sh
#
# Nothing here is manual and nothing here needs conda. Re-running is safe: it
# finds what is already installed and leaves it alone.
#
#   CAVER 3.0   GPLv3, Masaryk University. Downloaded from caver.cz. Not
#               committed, because this repository is Apache-2.0 and shipping
#               copyleft jars inside it is a licensing mess -- and iGEM asks
#               that source produce the output rather than committed binaries.
#   fpocket     MIT, Discngine. A C program, so there is no wheel for it. Built
#               from source here, which is exactly what "source produces the
#               output" means. conda is offered as a fallback, not required.
#
# Already have either? Point at it and this script will leave it be:
#   export CAVER_HOME=/opt/caver-3.0
#   export FPOCKET=/usr/local/bin/fpocket
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
THIRD_PARTY="$REPO_ROOT/third_party"

CAVER_URL="${CAVER_URL:-https://www.caver.cz/fil/download/caver30/302/caver_3.0.2.zip}"
# Pinned so a changed upstream file is noticed rather than silently installed.
# Verified 2026-10-10; these jars are byte-identical to the ones the project's
# published measurements were made with.
CAVER_SHA256="2d819541c7e3d3b223de18ba9a5bf2fbfaf92cced380d29e86cd749f7070ee1e"
CAVER_DEST="${CAVER_HOME:-$THIRD_PARTY/caver}"

FPOCKET_REPO="${FPOCKET_REPO:-https://github.com/Discngine/fpocket.git}"
FPOCKET_SRC="$THIRD_PARTY/fpocket"

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()   { printf '   \033[32mok\033[0m    %s\n' "$*"; }
warn() { printf '   \033[33mnote\033[0m  %s\n' "$*"; }
bad()  { printf '   \033[31mfail\033[0m  %s\n' "$*"; }

sha_of() {
    if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | cut -d' ' -f1
    elif command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
    else echo "UNVERIFIABLE"; fi
}

# ---------------------------------------------------------------- CAVER -----
say "CAVER 3.0"
if [ -f "$CAVER_DEST/caver.jar" ]; then
    ok "already present: $CAVER_DEST/caver.jar"
elif ! command -v curl >/dev/null 2>&1; then
    bad "curl not found; download $CAVER_URL by hand into $CAVER_DEST"
else
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT
    echo "   downloading (33 MB) ..."
    # --no-progress-meter: the default meter writes thousands of \r-separated
    # updates, which is unreadable in a log or a CI transcript.
    if ! curl -fSL --no-progress-meter --retry 3 --retry-delay 2 \
             "$CAVER_URL" -o "$tmp/caver.zip"; then
        bad "download failed. Fetch $CAVER_URL by hand and unpack so that"
        bad "$CAVER_DEST/caver.jar exists, or set \$CAVER_HOME."
    else
        got="$(sha_of "$tmp/caver.zip")"
        if [ "$got" = "UNVERIFIABLE" ]; then
            warn "no sha256 tool; skipping checksum"
        elif [ "$got" != "$CAVER_SHA256" ]; then
            bad "checksum mismatch -- NOT installing."
            bad "  expected $CAVER_SHA256"
            bad "  got      $got"
            bad "Upstream may have changed the file. Check caver.cz before using it."
            got="BAD"
        fi
        if [ "${got:-}" != "BAD" ]; then
            mkdir -p "$CAVER_DEST"
            # The archive nests everything under caver_3.0/caver/; flatten it so
            # that $CAVER_HOME/caver.jar and $CAVER_HOME/lib/ are where
            # enzyme_design/lib/paths.py expects them.
            unzip -q "$tmp/caver.zip" -d "$tmp/x"
            inner="$(dirname "$(find "$tmp/x" -name caver.jar -print -quit)")"
            if [ -z "$inner" ]; then
                bad "no caver.jar inside the archive -- layout changed upstream?"
            else
                cp -R "$inner/." "$CAVER_DEST/"
                ok "installed to $CAVER_DEST"
                ok "GPLv3 (Masaryk University). Cite Chovancova et al. (2012)"
                ok "PLoS Comput Biol 8(10):e1002708 if you publish with it."
            fi
        fi
    fi
    rm -rf "$tmp"; trap - EXIT
fi

# -------------------------------------------------------------- fpocket -----
say "fpocket"
if [ -n "${FPOCKET:-}" ] && [ -x "${FPOCKET:-}" ]; then
    ok "using \$FPOCKET: $FPOCKET"
elif command -v fpocket >/dev/null 2>&1; then
    ok "already on PATH: $(command -v fpocket)"
elif [ -x "$FPOCKET_SRC/bin/fpocket" ]; then
    ok "already built: $FPOCKET_SRC/bin/fpocket"
    warn "add it to PATH:  export PATH=\"$FPOCKET_SRC/bin:\$PATH\""
elif ! command -v make >/dev/null 2>&1 || ! command -v cc >/dev/null 2>&1; then
    bad "no C toolchain (need make and cc) -- cannot build from source."
    bad "Install a prebuilt one instead:  conda install -c bioconda fpocket"
else
    if [ ! -d "$FPOCKET_SRC/.git" ]; then
        echo "   cloning $FPOCKET_REPO ..."
        git clone --depth 1 -q "$FPOCKET_REPO" "$FPOCKET_SRC" || bad "clone failed"
    fi
    if [ -d "$FPOCKET_SRC" ]; then
        echo "   building (a minute or two) ..."
        if make -C "$FPOCKET_SRC" -j"$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)" \
               >"$FPOCKET_SRC/build.log" 2>&1 && [ -x "$FPOCKET_SRC/bin/fpocket" ]; then
            ok "built: $FPOCKET_SRC/bin/fpocket"
            warn "add it to PATH:  export PATH=\"$FPOCKET_SRC/bin:\$PATH\""
        else
            bad "build failed; see $FPOCKET_SRC/build.log"
            case "$(uname -s)" in
                Darwin)
                    warn "On macOS this usually fails in fpocket's bundled qhull"
                    warn "(\"libqhull/libqhull.h file not found\"). Known upstream"
                    warn "issue, not something this project can patch around."
                    warn "Use a prebuilt one instead:"
                    warn "  conda install -c bioconda fpocket"
                    warn "  brew install fpocket        # if your tap has it"
                    ;;
                *)
                    warn "Install a prebuilt one instead:"
                    warn "  conda install -c bioconda fpocket"
                    ;;
            esac
            warn "Only the POCKET stage needs fpocket. Tunnel measurement does not."
        fi
    fi
fi

# ----------------------------------------------------------------- Java -----
say "Java (CAVER 3.0 wants 8)"
if command -v java >/dev/null 2>&1; then
    v="$(java -version 2>&1 | head -1)"
    ok "$v"
    case "$v" in
        *1.8*|*\"8*) ;;
        *) warn "CAVER 3.0 is a Java 8 application; newer JDKs usually work but" ;;
    esac
else
    bad "no java. Any JDK will do; 8 is what CAVER was built against."
fi

# -------------------------------------------------------------- summary -----
say "Summary"
have_caver=0; have_fpocket=0; have_java=0
[ -f "$CAVER_DEST/caver.jar" ] && have_caver=1
{ command -v fpocket >/dev/null 2>&1 || [ -x "$FPOCKET_SRC/bin/fpocket" ] \
  || { [ -n "${FPOCKET:-}" ] && [ -x "${FPOCKET:-}" ]; }; } && have_fpocket=1
command -v java >/dev/null 2>&1 && have_java=1

printf '   CAVER   %s\n   fpocket %s\n   java    %s\n' \
  "$([ $have_caver = 1 ] && echo yes || echo MISSING)" \
  "$([ $have_fpocket = 1 ] && echo yes || echo MISSING)" \
  "$([ $have_java = 1 ] && echo yes || echo MISSING)"

if [ $have_caver = 1 ] && [ $have_java = 1 ]; then
    echo
    ok "Tunnel measurement can run."
    [ $have_fpocket = 1 ] || warn "fpocket is only needed for the pocket stage."
    exit 0
fi
echo
bad "Tunnel measurement needs CAVER and java (see above)."
exit 1
