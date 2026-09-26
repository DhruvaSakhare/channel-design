"""
The two components must still find each other.

enzyme_design/ measures channels using code and configuration that live in
channel_discovery/. Before publication those two sat inside one directory and
the link was a relative path (`parent.parent / "channel_discovery"`). They are
now separate top-level components, so that link is resolved in lib/paths.py --
and it breaks silently, in the middle of a GPU run, if it is ever wrong.
"""
import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import REPO_ROOT

CROSS_COMPONENT_SCRIPTS = (
    "02b_caver_filter", "07_caver_rescore", "08_probe_channel",
    "09_compare_to_parent",
)


@pytest.fixture()
def paths():
    sys.path.insert(0, str(REPO_ROOT / "enzyme_design" / "lib"))
    for name in ("CHANNEL_DESIGN_ROOT", "CAVER_HOME", "CAVER_JAR", "CAVER_LIB"):
        os.environ.pop(name, None)
    mod = importlib.import_module("paths")
    return importlib.reload(mod)


def test_repo_root_is_the_checkout(paths):
    assert paths.REPO_ROOT == REPO_ROOT


def test_cross_component_targets_exist(paths):
    assert paths.CHANNEL_ROOT.is_dir(), paths.CHANNEL_ROOT
    assert paths.FPOCKET_ROOT.is_dir(), paths.FPOCKET_ROOT
    assert paths.CIF_TO_PDB.is_file(), (
        f"the mmCIF converter the design stages call is missing: {paths.CIF_TO_PDB}")
    assert paths.CAVER_CONFIG.is_file(), paths.CAVER_CONFIG


def test_caver_is_expected_outside_the_repository(paths):
    """CAVER is GPLv3 and fetched, so it must not be looked for in-tree."""
    assert "third_party" in str(paths.CAVER_HOME)
    assert not paths.CAVER_JAR.exists() or paths.CAVER_JAR.is_file()


def test_environment_overrides_win(tmp_path):
    code = ("import paths; print(paths.CAVER_HOME); print(paths.REPO_ROOT)")
    env = dict(os.environ,
               CAVER_HOME=str(tmp_path / "my-caver"),
               PYTHONPATH=str(REPO_ROOT / "enzyme_design" / "lib"))
    out = subprocess.run([sys.executable, "-c", code],
                         capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    caver_home = out.stdout.splitlines()[0]
    assert caver_home == str(tmp_path / "my-caver")


@pytest.mark.parametrize("name", CROSS_COMPONENT_SCRIPTS)
def test_cross_component_scripts_import(name, tmp_path):
    """These four reach across to channel_discovery; import catches a bad path."""
    script = (REPO_ROOT / "enzyme_design" / "partial_diffusion" / "scripts"
              / f"{name}.py")
    code = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('m', {str(script)!r})\n"
        "m = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(m)\n"
        "print(m.CIF_TO_PDB)\n"
    )
    env = dict(os.environ, PIPELINE_WORK_ROOT=str(tmp_path))
    out = subprocess.run([sys.executable, "-c", code],
                         capture_output=True, text=True, env=env)
    assert out.returncode == 0, f"{name} failed to import:\n{out.stderr}"
    assert Path(out.stdout.strip().splitlines()[-1]).is_file()
