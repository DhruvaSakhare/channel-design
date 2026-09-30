"""
A fresh clone must work before anything is configured.

config.py is the user's own working copy, made by copying config_template.py,
and is deliberately not in the repository. The stage scripts used to default
straight to it, so on a clean checkout the first command anyone tried --
`run_local.py --help` -- died with an import error. That is the worst possible
first impression for someone evaluating this, so it is asserted here.
"""
import os
import subprocess
import sys

import pytest

from conftest import REPO_ROOT

SCRIPTS = REPO_ROOT / "enzyme_design" / "partial_diffusion" / "scripts"

# The commands a newcomer actually types first. Each must answer --help with
# exit 0 on a clone where no config.py exists.
ENTRY_POINTS = ("run_local.py", "00_submit_all.py", "07_caver_rescore.py",
                "08_probe_channel.py", "12_bottleneck_residues.py")


def _env(tmp_path):
    env = dict(os.environ, PIPELINE_WORK_ROOT=str(tmp_path))
    env.pop("PIPELINE_BASE_CONFIG", None)   # simulate an unconfigured clone
    return env


def test_config_py_is_not_shipped():
    """If this ever fails, someone committed their working config."""
    assert not (REPO_ROOT / "enzyme_design" / "partial_diffusion" / "config.py").exists(), (
        "config.py is a personal working copy and must not be committed")


def test_default_config_resolves_without_a_config_py(tmp_path):
    code = (
        "import partial_diffusion, importlib\n"
        "name = partial_diffusion.default_config()\n"
        "importlib.import_module(name)\n"      # must actually be importable
        "print(name)\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        env=dict(_env(tmp_path), PYTHONPATH=str(REPO_ROOT / "enzyme_design")),
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "partial_diffusion.config_template", (
        f"unconfigured clone resolved to {out.stdout.strip()!r}")


def test_environment_variable_still_wins(tmp_path):
    code = "import partial_diffusion; print(partial_diffusion.default_config())"
    env = dict(_env(tmp_path),
               PYTHONPATH=str(REPO_ROOT / "enzyme_design"),
               PIPELINE_BASE_CONFIG="partial_diffusion.configs.config_grogu")
    out = subprocess.run([sys.executable, "-c", code],
                         capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "partial_diffusion.configs.config_grogu"


@pytest.mark.parametrize("script", ENTRY_POINTS)
def test_entry_point_answers_help(script, tmp_path):
    out = subprocess.run(
        [sys.executable, str(SCRIPTS / script), "--help"],
        capture_output=True, text=True, env=_env(tmp_path),
    )
    assert out.returncode == 0, (
        f"{script} --help failed on an unconfigured clone:\n{out.stderr[-600:]}")
    assert "usage" in out.stdout.lower()
