import subprocess
import sys
from pathlib import Path

# Stock macOS ships Python 3.9 as `python3`, and the pinned test dependencies
# need 3.10 or newer -- so the first command in the README used to fail with a
# wall of pip version errors. Say so plainly instead.
if sys.version_info < (3, 12):
    raise SystemExit(
        f"This project needs Python 3.12 or newer; you are running "
        f"{sys.version.split()[0]} from {sys.executable}.\n"
        "\n"
        "On macOS `python3` is often the system 3.9. Make a virtual "
        "environment with a newer one:\n"
        "    python3.12 -m venv .venv && source .venv/bin/activate\n"
        "    pip install -r envs/requirements-tests.txt\n"
    )

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"

# The pipeline is a set of scripts, not an installed package; these are the
# same two entries the stage scripts put on sys.path themselves.
sys.path.insert(0, str(REPO_ROOT / "enzyme_design"))
sys.path.insert(0, str(REPO_ROOT / "enzyme_design" / "lib"))


# Directories that never hold source we ship, used when git is unavailable.
_SKIP_DIRS = {
    ".git", "__pycache__", ".pytest_cache", ".venv", "venv", "third_party",
    "work", "outputs", ".idea", ".vscode", ".mypy_cache", ".ruff_cache",
}


def repo_files(pattern="*"):
    """Every file this repository ships, as absolute paths.

    Prefers `git ls-files`, which knows exactly what is tracked. Falls back to
    walking the tree when git is absent -- the CI image has no git, and the
    tests should also work for someone who downloaded a zip rather than
    cloning. The fallback skips build and output directories so the two answers
    agree in practice.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", pattern],
            capture_output=True, text=True, check=True,
        )
        # Filter to what is actually on disk: `git ls-files` still lists a
        # file that has been deleted but not yet staged, and the suite should
        # not break halfway through an edit.
        return [p for p in (REPO_ROOT / line for line in out.stdout.splitlines() if line)
                if p.is_file()]
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    return [
        path for path in sorted(REPO_ROOT.rglob(pattern))
        if path.is_file()
        and not any(part in _SKIP_DIRS for part in path.relative_to(REPO_ROOT).parts)
    ]
