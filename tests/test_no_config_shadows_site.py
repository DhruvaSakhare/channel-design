"""
No experiment config may redefine a machine-layer name.

`site.py` is the machine layer: install paths, checkpoints, queue names. The
configs are the experiment layer. The separation is the reason an experiment
config can be published without publishing somebody's filesystem.

It was not enforced, and it broke exactly where you would expect. Every config
carried its own `QUEUE = "gpua100"` literal, so:

  * `site.QUEUE` resolved `PIPELINE_QUEUE` correctly,
  * nothing imported it -- `site.QUEUE` was dead code,
  * `00_submit_all.py` read `C.QUEUE` from the config, and the literal won.

`PIPELINE_QUEUE=gpuv100` therefore printed `gpuv100` from site.py's own
`--check` output and submitted to `gpua100`, with no warning. The comment
directly above the literal said "queue names live in site.py, not here".

A name defined in both places is ambiguous whichever one wins, so this asserts
there are none.
"""
import ast
import importlib.util

import pytest

from conftest import REPO_ROOT

PD = REPO_ROOT / "enzyme_design" / "partial_diffusion"
SITE = PD / "site.py"
CONFIGS = [PD / "config_template.py"] + sorted((PD / "configs").glob("config_*.py"))

# Names site.py defines that are plumbing, not configuration.
NOT_SETTINGS = {"REPO_ROOT", "Path", "os", "describe"}


def _module_level_assignments(path):
    """Names bound at module level by a plain assignment."""
    names = set()
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _imported_from_site(path):
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("site"):
            return {a.name for a in node.names}
    return set()


SITE_SETTINGS = _module_level_assignments(SITE) - NOT_SETTINGS


def test_site_defines_the_settings_we_think_it_does():
    """A tripwire on the tripwire: if site.py is renamed or gutted, the tests
    below would pass vacuously."""
    for expected in ("QUEUE", "CPU_QUEUE", "RFD3_CKPT", "MPNN_CKPT",
                     "RF3_RELEASE", "RF3_CKPT", "SHARED_ROOT"):
        assert expected in SITE_SETTINGS, f"site.py no longer defines {expected}"


@pytest.mark.parametrize("config", CONFIGS, ids=lambda p: p.name)
def test_config_does_not_shadow_site(config):
    shadowed = _module_level_assignments(config) & SITE_SETTINGS
    # Re-applying the frozen run snapshot is a deliberate re-assignment, and it
    # happens inside `if _SNAPSHOT_PATH:` -- not at module level -- so it does
    # not show up here. Anything that does is a literal competing with site.py.
    assert not shadowed, (
        f"{config.name} assigns {sorted(shadowed)} at module level, which "
        "site.py also defines. Whichever wins, the other is a lie: import it "
        "from site.py instead.")


@pytest.mark.parametrize("config", CONFIGS, ids=lambda p: p.name)
def test_config_imports_the_queues_from_site(config):
    """Specifically the two that were wrong, since a missing import is silent:
    the config simply would not define QUEUE and the error would surface as an
    AttributeError deep in a submit script."""
    imported = _imported_from_site(config)
    missing = {"QUEUE", "CPU_QUEUE"} - imported
    assert not missing, f"{config.name} does not import {sorted(missing)} from site.py"


def test_site_queues_are_actually_consumed():
    """site.QUEUE was dead code for as long as it existed. If nothing imports
    it, `PIPELINE_QUEUE` is decoration."""
    consumers = [c.name for c in CONFIGS if "QUEUE" in _imported_from_site(c)]
    assert consumers, (
        "no config imports QUEUE from site.py, so PIPELINE_QUEUE cannot "
        "affect any run -- site.py's queue settings would be dead code again")


# ---------------------------------------------------------------------------
# And no cluster's queue names may be the default.
#
# `QUEUE` defaulted to `gpua100` and `CPU_QUEUE` to `hpc` -- DTU queue names,
# baked into the machine layer the same way a DTU path would have been, except
# that nothing can check a queue name exists. `gpua100` was also DTU's most
# contended queue (694 jobs deep when measured) while this repository's own
# README said the two GPU queues are interchangeable.
#
# tests/test_no_machine_paths.py catches a cluster path. This catches the same
# mistake wearing a different hat.
# ---------------------------------------------------------------------------

# DTU's own names. Deliberately not exhaustive -- it does not need to be, it
# needs to catch the ones that were actually baked in. Note that DTU course-code
# queues are NOT listed: tests/test_no_machine_paths.py forbids that pattern
# repo-wide, and it fails on this file if one appears here. It caught exactly
# that while this test was being written, which is the system working.
KNOWN_QUEUE_NAMES = ("gpua100", "gpuv100", "gpuamd", "hpc")


def _default_of(name):
    """The literal default in site.py's `_env(VAR, default)` call."""
    for node in ast.walk(ast.parse(SITE.read_text())):
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "id", None) == name for t in node.targets)
                and isinstance(node.value, ast.Call)
                and getattr(node.value.func, "id", None) == "_env"):
            default = node.value.args[1]
            return default.value if isinstance(default, ast.Constant) else default
    raise AssertionError(f"site.py has no _env(...) assignment for {name}")


@pytest.mark.parametrize("name", ["QUEUE", "CPU_QUEUE"])
def test_queue_has_no_baked_default(name):
    default = _default_of(name)
    assert default == "", (
        f"site.{name} defaults to {default!r}. A queue name is as "
        "site-specific as a path, and unlike a path nothing here can check it "
        "exists -- a wrong one fails in the scheduler or, worse, succeeds on "
        "the wrong hardware. Leave it empty; 00_submit_all.py refuses to "
        "submit without one and says how to set it.")


def test_submit_refuses_without_a_queue():
    """The guard, not just the empty default: an empty queue must not reach
    `#BSUB -q`."""
    src = (PD / "scripts" / "00_submit_all.py").read_text()
    assert "sys.exit(2)" in src, "00_submit_all.py has no hard exit for a missing queue"
    assert "bqueues" in src, (
        "the missing-queue error should name `bqueues` -- the user has no "
        "other way to find out what their cluster calls its queues")


def test_no_queue_name_is_hardcoded_in_a_config_or_site_default():
    """Belt and braces: the names themselves, anywhere they could win."""
    offenders = []
    for path in [SITE, *CONFIGS]:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Constant) and node.value in KNOWN_QUEUE_NAMES:
                offenders.append(f"{path.name}:{node.lineno} = {node.value!r}")
    assert not offenders, (
        "cluster queue names appear as string literals in the config or "
        "machine layer:\n  " + "\n  ".join(offenders) +
        "\nThey belong in envs/site.env, PIPELINE_QUEUE, or --queue.")
