"""
Flags named in the documentation must exist.

README, docs/ and the agent skill all told people to run
`00_submit_all.py --dry-run`. That flag had never existed -- not in the
published repo and not in the pre-publication source. It was documented in four
places on the strength of a plausible assumption, and the error surfaced only
when somebody on a cluster actually typed it.

Documentation is not checkable in general, but *this* class of claim is: a
flag either appears in `--help` or it does not.
"""
import re
import subprocess
import sys

import pytest

from conftest import REPO_ROOT, repo_files

# Entry points whose --help we can obtain without a GPU, a cluster or weights.
ENTRY_POINTS = {
    "00_submit_all.py":  REPO_ROOT / "enzyme_design/partial_diffusion/scripts/00_submit_all.py",
    "run_local.py":      REPO_ROOT / "enzyme_design/partial_diffusion/scripts/run_local.py",
    "boltz_template_batch.py": REPO_ROOT / "boltz/boltz_template_batch.py",
}

# Flags the docs promise for each. Keep this list short and real: it is a
# tripwire for "we wrote it down but never ran it", not a CLI spec.
PROMISED = {
    "00_submit_all.py": ["--dry-run", "--pilot", "--experiment", "--flexible"],
    "run_local.py": ["--dry-run", "--check", "--stages", "--skip-preflight"],
    "boltz_template_batch.py": ["--resume", "--template", "--fasta", "--out_dir"],
}


def _help_text(path):
    out = subprocess.run([sys.executable, str(path), "--help"],
                         capture_output=True, text=True)
    assert out.returncode == 0, f"{path.name} --help failed:\n{out.stderr[-500:]}"
    return out.stdout


@pytest.mark.parametrize("name", sorted(PROMISED))
def test_promised_flags_exist(name):
    text = _help_text(ENTRY_POINTS[name])
    missing = [f for f in PROMISED[name] if f not in text]
    assert not missing, f"{name} --help does not offer {missing}"


def test_dry_run_is_offered_by_both_drivers():
    """The two drivers are meant to be interchangeable bar the scheduler, so a
    flag this important should not exist in only one of them."""
    for name in ("00_submit_all.py", "run_local.py"):
        assert "--dry-run" in _help_text(ENTRY_POINTS[name]), (
            f"{name} has no --dry-run; the other driver does")


def test_no_doc_mentions_a_flag_that_does_not_exist():
    """Scan docs for `<script> --flag` and check each against --help."""
    pattern = re.compile(r"(00_submit_all\.py|run_local\.py)\s+((?:--[a-z][a-z0-9-]*\s*)+)")
    helps = {n: _help_text(p) for n, p in ENTRY_POINTS.items()}
    offenders = []
    for path in repo_files("*.md"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for script, flags in pattern.findall(text):
            for flag in flags.split():
                if flag.startswith("--") and flag not in helps[script]:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}: {script} {flag}")
    assert not offenders, "docs name flags that do not exist:\n  " + "\n  ".join(offenders)
