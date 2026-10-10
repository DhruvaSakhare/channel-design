#!/usr/bin/env bash
# Set this project up, start to finish. No conda required.
#
#   ./setup.sh                # the CPU half: tests + channel measurement
#   ./setup.sh --gpu          # also the GPU stages (Boltz-2, RFdiffusion3/RF3)
#   ./setup.sh --check        # report what is present; install nothing
#
# What it does, in order:
#   1. uv          -- installs it if you do not have it (asks first)
#   2. Python deps -- from the committed uv.lock, so versions are exact
#   3. CAVER 3.0   -- downloaded from caver.cz, checksum verified
#   4. fpocket     -- built from source (it is a C program; there is no wheel)
#   5. Java        -- checked, not installed; any JDK will do
#
# Safe to re-run: anything already present is left alone. Set $CAVER_HOME or
# $FPOCKET to point at copies you already have and they will be used as-is.
#
# The one thing this does NOT fetch is model weights for the design stages --
# tens of GB, and only needed if you are redesigning rather than measuring:
#   uv run foundry install base-models --checkpoint-dir ./ckpt
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

WANT_GPU=0
CHECK_ONLY=0
ASSUME_YES=0
for arg in "$@"; do
    case "$arg" in
        --gpu)   WANT_GPU=1 ;;
        --check) CHECK_ONLY=1 ;;
        -y|--yes) ASSUME_YES=1 ;;
        -h|--help) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
    esac
done

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()   { printf '   \033[32mok\033[0m    %s\n' "$*"; }
warn() { printf '   \033[33mnote\033[0m  %s\n' "$*"; }
bad()  { printf '   \033[31mfail\033[0m  %s\n' "$*"; }

ask() {   # ask "question" -> 0 if yes
    [ "$ASSUME_YES" = 1 ] && return 0
    [ -t 0 ] || return 1          # non-interactive: decline rather than hang
    printf '   %s [y/N] ' "$1"; read -r reply
    case "$reply" in [Yy]*) return 0 ;; *) return 1 ;; esac
}

# ------------------------------------------------------------------- uv -----
say "uv"
if command -v uv >/dev/null 2>&1; then
    ok "$(uv --version)"
elif [ "$CHECK_ONLY" = 1 ]; then
    bad "not installed"
else
    warn "uv is not installed. It manages Python and every dependency here."
    warn "Installer: https://astral.sh/uv/install.sh  (from Astral, uv's authors)"
    if ask "Download and run it?"; then
        curl -fsSL https://astral.sh/uv/install.sh | sh || bad "install failed"
        export PATH="$HOME/.local/bin:$PATH"
        command -v uv >/dev/null 2>&1 && ok "$(uv --version)" \
            || bad "uv still not on PATH; open a new shell and re-run"
    else
        bad "skipped. Install it yourself, then re-run:"
        bad "  curl -fsSL https://astral.sh/uv/install.sh | sh"
    fi
fi

# --------------------------------------------------------- python deps -----
say "Python dependencies"
if ! command -v uv >/dev/null 2>&1; then
    bad "needs uv (above)"
elif [ "$CHECK_ONLY" = 1 ]; then
    [ -d .venv ] && ok ".venv exists" || warn ".venv not created yet"
else
    extras=(--extra tests --extra docking)
    [ "$WANT_GPU" = 1 ] && extras+=(--extra boltz --extra design)
    echo "   uv sync ${extras[*]}"
    if uv sync "${extras[@]}"; then
        ok "installed from uv.lock"
        [ "$WANT_GPU" = 1 ] && warn "install torch for YOUR CUDA before using the GPU stages:
          uv pip install torch --index-url https://download.pytorch.org/whl/cu128"
    else
        bad "uv sync failed"
        warn "On macOS arm64 the docking extra needs boost for the vina build:"
        warn "  brew install boost   (Linux x86_64 uses a prebuilt wheel instead)"
    fi
fi

# ------------------------------------------------- CAVER and fpocket -------
if [ "$CHECK_ONLY" = 1 ]; then
    CAVER_DEST="${CAVER_HOME:-$REPO_ROOT/third_party/caver}"
    say "External tools"
    [ -f "$CAVER_DEST/caver.jar" ] && ok "CAVER: $CAVER_DEST" || bad "CAVER: missing"
    command -v fpocket >/dev/null 2>&1 && ok "fpocket: $(command -v fpocket)" \
        || { [ -x third_party/fpocket/bin/fpocket ] && ok "fpocket: built, not on PATH" \
             || bad "fpocket: missing"; }
    command -v java >/dev/null 2>&1 && ok "java: $(java -version 2>&1 | head -1)" \
        || bad "java: missing"
else
    # One implementation of this, in scripts/fetch_third_party.sh -- it is also
    # the thing to run on its own when only the tools are missing.
    ./scripts/fetch_third_party.sh
fi

# -------------------------------------------------------------- what next ---
say "Next"
cat <<'TXT'
   Check it works, no GPU and no external tools needed:
       uv run --extra tests pytest -q

   Measure a tunnel in your own structure:
       uv run python enzyme_design/partial_diffusion/scripts/00_caver_channel.py <file.pdb>

   The full walkthrough, including the GPU stages:
       docs/walkthrough-gpu.md
TXT
