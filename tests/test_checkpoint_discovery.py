"""
Checkpoints are found, not configured.

They are large and usually already on a shared filesystem, so site.py searches
$CKPT_SEARCH_PATH before falling back to <repo>/ckpt. The thing to guard is
that the search list stays empty by default: baking a cluster path into
published code is exactly what test_no_machine_paths.py forbids, and this is
where it would be tempting to add one.
"""
import os
import subprocess
import sys

from conftest import REPO_ROOT

ENZYME = str(REPO_ROOT / "enzyme_design")


def _resolve(env):
    code = (
        "import sys; sys.path.insert(0, %r)\n"
        "from partial_diffusion import site\n"
        "print(site.RFD3_CKPT); print(site.MPNN_CKPT)\n"
        "print(site.RF3_RELEASE); print(site.RF3_CKPT)\n" % ENZYME
    )
    base = {k: v for k, v in os.environ.items()
            if k not in ("CKPT_SEARCH_PATH", "RFD3_CKPT", "MPNN_CKPT",
                         "RF3_CKPT", "RF3_RELEASE")}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, env={**base, **env})
    assert out.returncode == 0, out.stderr
    return out.stdout.split()


def test_no_search_path_is_baked_in():
    """The default must search nowhere -- no cluster filesystem in the repo."""
    rfd3, mpnn, release, rf3 = _resolve({})
    for value in (rfd3, mpnn, release, rf3):
        assert value.startswith(str(REPO_ROOT)), (
            f"default resolved outside the repository: {value}")


def test_search_path_is_used(tmp_path):
    shared = tmp_path / "foundry" / "ckpt"
    shared.mkdir(parents=True)
    (shared / "rfd3_latest.ckpt").touch()
    (shared / "ligandmpnn_v_32_010_25.pt").touch()

    rfd3, mpnn, _, _ = _resolve({"CKPT_SEARCH_PATH": str(shared)})
    assert rfd3 == str(shared / "rfd3_latest.ckpt")
    assert mpnn == str(shared / "ligandmpnn_v_32_010_25.pt")


def test_rf3_release_is_derived_from_its_ckpt_dir(tmp_path):
    """A release tree is <dir>/ckpt/rf3_latest.pt; pointing at the ckpt dir
    should still yield the tree, since RF3 needs the tree and not just the
    weights."""
    release = tmp_path / "rf3" / "release"
    (release / "ckpt").mkdir(parents=True)
    (release / "ckpt" / "rf3_latest.pt").touch()

    _, _, found_release, found_ckpt = _resolve(
        {"CKPT_SEARCH_PATH": str(release / "ckpt")})
    assert found_release == str(release)
    assert found_ckpt == str(release / "ckpt" / "rf3_latest.pt")


def test_explicit_variable_beats_the_search(tmp_path):
    shared = tmp_path / "ckpt"
    shared.mkdir()
    (shared / "rfd3_latest.ckpt").touch()

    rfd3, _, _, _ = _resolve({"CKPT_SEARCH_PATH": str(shared),
                              "RFD3_CKPT": "/explicit/override.ckpt"})
    assert rfd3 == "/explicit/override.ckpt"


def test_missing_checkpoints_are_flagged_in_the_report():
    """site.py --describe must say a path does not exist, not just print it."""
    code = ("import sys; sys.path.insert(0, %r)\n"
            "from partial_diffusion import site; print(site.describe())\n" % ENZYME)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, env={k: v for k, v in os.environ.items()
                                         if k != "CKPT_SEARCH_PATH"})
    assert out.returncode == 0, out.stderr
    assert "DOES NOT EXIST" in out.stdout, (
        "a fresh clone has no checkpoints; the report should say so")
