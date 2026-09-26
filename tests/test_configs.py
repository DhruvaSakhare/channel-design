"""
Every shipped config must import, and must not write outside the work root.

Configs are plain Python that runs at import time: they read the input PDB,
derive catalytic residues and build output paths. That means a broken one
fails only when somebody tries to use it, which is how eleven team configs
came to be unrunnable at once. Importing them all here makes that a test.

The second assertion is the privacy one. A config must resolve its output
under $PIPELINE_WORK_ROOT and nowhere else, so publishing a config can never
publish somebody's scratch directory.
"""
import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import REPO_ROOT

CONFIG_DIR = REPO_ROOT / "enzyme_design" / "partial_diffusion" / "configs"
TEMPLATE = REPO_ROOT / "enzyme_design" / "partial_diffusion" / "config_template.py"

MODULES = [f"partial_diffusion.configs.{p.stem}"
           for p in sorted(CONFIG_DIR.glob("config_*.py"))]
MODULES.append("partial_diffusion.config_template")


def _import_in_subprocess(module, work_root):
    """Each config is imported in its own process: they share a module name
    space and several mutate it at import time."""
    code = (
        "import importlib, pathlib, sys\n"
        f"m = importlib.import_module({module!r})\n"
        "print(m.WORK)\n"
        "print(m.INPUT_PDB)\n"
    )
    env = dict(os.environ,
               PIPELINE_WORK_ROOT=str(work_root),
               PIPELINE_BASE_CONFIG=module,
               PYTHONPATH=str(REPO_ROOT / "enzyme_design"))
    return subprocess.run([sys.executable, "-c", code],
                          capture_output=True, text=True, env=env)


def test_there_are_configs_to_check():
    assert len(MODULES) > 1, "no example configs found"


@pytest.mark.parametrize("module", MODULES, ids=lambda m: m.rsplit(".", 1)[-1])
def test_config_imports_and_stays_inside_the_work_root(module, tmp_path):
    result = _import_in_subprocess(module, tmp_path)
    assert result.returncode == 0, f"{module} failed to import:\n{result.stderr}"

    work, input_pdb = result.stdout.strip().splitlines()[:2]

    assert Path(work).is_relative_to(tmp_path), (
        f"{module} resolved WORK to {work}, outside $PIPELINE_WORK_ROOT")
    assert Path(input_pdb).exists(), (
        f"{module} points at a missing structure: {input_pdb}")


def test_site_defaults_are_inside_the_repository():
    """With no environment set, nothing may point off the checkout."""
    sys.path.insert(0, str(REPO_ROOT / "enzyme_design"))
    for name in ("CONDA_SH", "PROTEIN_ENV", "RFD3_CKPT", "MPNN_CKPT",
                 "RF3_RELEASE", "RF3_CKPT", "PIPELINE_WORK_ROOT",
                 "PIPELINE_QUEUE", "PIPELINE_CPU_QUEUE"):
        os.environ.pop(name, None)
    site = importlib.import_module("partial_diffusion.site")
    importlib.reload(site)

    for name in ("RFD3_CKPT", "MPNN_CKPT", "RF3_RELEASE", "RF3_CKPT"):
        value = Path(getattr(site, name))
        assert value.is_relative_to(REPO_ROOT), f"{name} defaults to {value}"
    assert Path(site.SHARED_ROOT).is_relative_to(REPO_ROOT)
    # Empty means "the environment is already active", not a path.
    assert site.CONDA_SH == "" and site.PROTEIN_ENV == ""
