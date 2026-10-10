"""
The two drivers must run the same pipeline.

There are two ways to run the design loop: 00_submit_all.py submits it to LSF
as job arrays, run_local.py runs it on one GPU. They are meant to be the same
stages with the scheduler taken out.

They drifted. When the CAVER channel-width gate was added it went into the LSF
driver only, so for a long time a single-GPU run silently skipped it -- and
that gate is what makes this a measurement-driven loop rather than a plain
RFdiffusion -> LigandMPNN -> RF3 pipeline. Nothing failed; the stage was simply
absent, which is the kind of bug no amount of reading catches.

So it is asserted. If you add a stage to one driver, this fails until you add
it to the other or state here why it belongs to only one.
"""
import re

import pytest

from conftest import REPO_ROOT

SCRIPTS = REPO_ROOT / "enzyme_design" / "partial_diffusion" / "scripts"
LSF = SCRIPTS / "00_submit_all.py"
LOCAL = SCRIPTS / "run_local.py"

# The stages that do the pipeline's work. Both drivers must run all of them.
CORE_STAGES = (
    "01_rfd3_partial_submit.py",   # diffusion
    "02_rfd3_process.py",          # structural filter
    "02b_caver_filter.py",         # channel-width gate, before any GPU spend
    "03_mpnn_submit.py",           # sequence design
    "04_rf3_submit.py",            # folding
    "05_rf3_score.py",             # metrics
    "06_collect_best.py",          # collect winners
)

# Referenced by one driver only, for reasons rather than by accident:
#   00_prep_pdb.py      run_local's own prep stage; the LSF path validates
#                       inside the submit step instead.
#   00_caver_channel.py these are *suggestions* printed to the user by
#   08_probe_channel.py 00_submit_all.py, not stages it runs.
#   00_make_msa.py      optional, driven by --auto-msa / run by hand.
EXPECTED_ASYMMETRY = {
    "00_prep_pdb.py", "00_caver_channel.py", "08_probe_channel.py",
    "00_make_msa.py", "00_submit_all.py", "run_local.py",
}

SCRIPT_RE = re.compile(r"\b(\d\d[a-z0-9_]*\.py)\b")


def _referenced(path):
    """Stage scripts this driver actually runs.

    Comment lines are stripped first: a stage named only in a comment is not a
    stage that runs, and counting prose let the first version of this test pass
    against a driver that had the gate described but not wired up.
    """
    code = "\n".join(
        line for line in path.read_text().splitlines()
        if not line.lstrip().startswith("#")
    )
    return set(SCRIPT_RE.findall(code))


@pytest.mark.parametrize("stage", CORE_STAGES)
def test_lsf_driver_runs_stage(stage):
    assert stage in _referenced(LSF), f"{LSF.name} does not run {stage}"


@pytest.mark.parametrize("stage", CORE_STAGES)
def test_local_driver_runs_stage(stage):
    assert stage in _referenced(LOCAL), (
        f"run_local.py does not run {stage} -- a single-GPU run would skip it")


def test_no_unexplained_difference_between_drivers():
    diff = _referenced(LSF) ^ _referenced(LOCAL)
    unexplained = diff - EXPECTED_ASYMMETRY
    assert not unexplained, (
        "these stage scripts are referenced by one driver but not the other, "
        f"and are not in EXPECTED_ASYMMETRY: {sorted(unexplained)}")


def test_every_stage_name_has_a_runner():
    """STAGES and the dispatch table are edited separately; keep them in step."""
    src = LOCAL.read_text()
    names = re.search(r"STAGES = \[(.*?)\]", src, re.S).group(1)
    names = re.findall(r'"([a-z_0-9]+)"', names)
    assert "caver_filter" in names, "the channel gate is not a stage"
    for name in names:
        assert f'"{name}":' in src, f"stage {name!r} has no entry in the runner map"


def test_all_referenced_stage_scripts_exist():
    for script in _referenced(LSF) | _referenced(LOCAL):
        if script == "run_local.py":
            continue
        assert (SCRIPTS / script).is_file(), f"{script} is referenced but missing"
