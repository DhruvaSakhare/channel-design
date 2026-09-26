"""
Every Python file in the repository must at least parse.

Cheap, but it is the test that catches a half-applied edit across twenty-odd
stage scripts, and it needs no dependencies at all -- so it runs in CI on a
bare python image where numpy and matplotlib are not installed.
"""
import py_compile
import subprocess

import pytest

from conftest import REPO_ROOT


def _tracked_python_files():
    out = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files", "*.py"],
                         capture_output=True, text=True, check=True)
    return [REPO_ROOT / line for line in out.stdout.splitlines() if line]


FILES = _tracked_python_files()


def test_there_are_sources():
    assert len(FILES) > 20, f"only found {len(FILES)} python files"


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_compiles(path, tmp_path):
    try:
        py_compile.compile(str(path), cfile=str(tmp_path / "out.pyc"),
                           doraise=True)
    except py_compile.PyCompileError as exc:
        pytest.fail(str(exc))
