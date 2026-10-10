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
