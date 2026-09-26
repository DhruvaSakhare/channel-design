#!/usr/bin/env python3
"""
Where everything lives.

The design pipeline (``enzyme_design/``) measures channels with code and data
that belong to the screening pipeline (``channel_discovery/``), and the two sit
side by side at the repository root. Every path that crosses that boundary
resolves through this module, so the layout is written down in exactly one
place instead of being re-derived with ``parents[n]`` in nine scripts.

CAVER itself is GPLv3 and is deliberately *not* redistributed here — see
``scripts/fetch_third_party.sh``. Anything below can be overridden from the
environment, which is how you point at a CAVER you already have:

    export CAVER_HOME=/opt/caver-3.0.3
"""
import os
from pathlib import Path


def _find_repo_root(start: Path) -> Path:
    """Walk up from `start` until the repository root is recognisable.

    The root is the directory holding both the licence and the screening
    pipeline. Falling back to two levels above ``lib/`` keeps this working if
    the tree is copied somewhere without the marker files.
    """
    for candidate in (start, *start.parents):
        if (candidate / "LICENSE").exists() and (candidate / "channel_discovery").is_dir():
            return candidate
    return start.parents[1]


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value) if value else default


REPO_ROOT = _env_path("CHANNEL_DESIGN_ROOT",
                      _find_repo_root(Path(__file__).resolve().parent))

# --- components -------------------------------------------------------------
ENZYME_DESIGN_ROOT = REPO_ROOT / "enzyme_design"
CHANNEL_ROOT       = REPO_ROOT / "channel_discovery" / "caver_pipeline"
FPOCKET_ROOT       = REPO_ROOT / "channel_discovery" / "fpocket_pipeline"
INPUTS_ROOT        = ENZYME_DESIGN_ROOT / "inputs"

# Used by 02b / 07 / 08 / 09 to turn RF3's mmCIF output into PDB for CAVER.
CIF_TO_PDB = CHANNEL_ROOT / "python_scripts" / "cif_to_pdb.py"

# --- CAVER (fetched, not vendored) ------------------------------------------
CAVER_HOME   = _env_path("CAVER_HOME", REPO_ROOT / "third_party" / "caver")
CAVER_JAR    = _env_path("CAVER_JAR", CAVER_HOME / "caver.jar")
CAVER_LIB    = _env_path("CAVER_LIB", CAVER_HOME / "lib")
CAVER_CONFIG = _env_path("CAVER_CONFIG", CHANNEL_ROOT / "config.txt")


def describe() -> str:
    """One line per resolved path — what `--check` prints."""
    return "\n".join(
        f"  {name:20s} {value}"
        for name, value in sorted(globals().items())
        if isinstance(value, Path) and name.isupper()
    )


if __name__ == "__main__":
    print("channel-design resolved paths:")
    print(describe())
