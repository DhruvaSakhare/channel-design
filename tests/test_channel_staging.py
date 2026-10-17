"""
Both channel entry points must apply the same two measurement rules.

docs/validation.md: a bound substrate narrows the measured bottleneck, and
CAVER's output depends on the input filename, each by more than the real
difference between structures. The rules were once enforced only on
the design side (enzyme_design/lib/caver_utils.py); channel_discovery's
run_batch.py silently carried both artifacts. These tests pin the shared
implementation and the run_batch behaviour, without needing CAVER installed.
"""
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import REPO_ROOT

SCRIPTS = REPO_ROOT / "channel_discovery" / "caver_pipeline" / "python_scripts"
sys.path.insert(0, str(SCRIPTS))

import staging  # noqa: E402
import run_batch  # noqa: E402
import caver_utils  # noqa: E402


def _atom(kind, serial, name, res, chain, num, x, element):
    return (f"{kind:<6}{serial:5d} {name:<4} {res:>3} {chain}{num:4d}    "
            f"{x:8.3f}{0:8.3f}{0:8.3f}  1.00  0.00          {element:>2}\n")


@pytest.fixture
def pdb_with_substrate(tmp_path):
    """Protein + heme + zinc + water + a docked substrate (UNL)."""
    lines = [
        _atom("ATOM", 1, "CA", "ALA", "A", 1, 1.0, "C"),
        _atom("ATOM", 2, "CA", "GLY", "A", 2, 2.0, "C"),
        _atom("HETATM", 3, "FE", "HEM", "B", 1, 3.0, "FE"),
        _atom("HETATM", 4, "ZN", "ZN", "C", 1, 4.0, "ZN"),
        _atom("HETATM", 5, "O", "HOH", "D", 1, 5.0, "O"),
        _atom("HETATM", 6, "C1", "UNL", "E", 1, 6.0, "C"),
        _atom("HETATM", 7, "C2", "UNL", "E", 1, 7.0, "C"),
        "END\n",
    ]
    path = tmp_path / "design_017.pdb"
    path.write_text("".join(lines))
    return path


def test_substrate_found_but_cofactors_kept(pdb_with_substrate):
    assert staging.substrate_resnames(pdb_with_substrate) == {"UNL"}


def test_extra_heme_alias_is_not_called_substrate(tmp_path):
    p = tmp_path / "x.pdb"
    p.write_text(_atom("HETATM", 1, "FE", "LIG", "B", 1, 1.0, "FE"))
    assert staging.substrate_resnames(p) == {"LIG"}            # unknown to staging
    assert staging.substrate_resnames(p, keep=run_batch.EXTRA_HEME_NAMES) == set()


def test_crystal_residues_are_not_called_substrate(tmp_path):
    """Glycans, modified amino acids and buffers are part of the crystal.

    Identifying the substrate by elimination used to delete all of these off a
    raw PDB entry and call the result "apo". MSE is the worst case: it sits in
    the backbone, so removing it leaves a hole that CAVER reads as channel.
    """
    p = tmp_path / "raw_crystal.pdb"
    p.write_text("".join([
        _atom("ATOM",   1, "CA", "ALA", "A", 1, 1.0, "C"),
        _atom("HETATM", 2, "FE", "HEM", "B", 1, 2.0, "FE"),
        _atom("HETATM", 3, "C1", "NAG", "C", 1, 3.0, "C"),   # N-linked glycan
        _atom("HETATM", 4, "C1", "BMA", "C", 2, 4.0, "C"),   # glycan
        _atom("HETATM", 5, "SE", "MSE", "A", 2, 5.0, "SE"),  # backbone residue
        _atom("HETATM", 6, "O",  "EPE", "D", 1, 6.0, "O"),   # HEPES buffer
        _atom("HETATM", 7, "C1", "PEG", "D", 2, 7.0, "C"),   # cryoprotectant
        _atom("HETATM", 8, "C1", "UNL", "E", 1, 8.0, "C"),   # the actual ligand
        "END\n",
    ]))
    assert staging.substrate_resnames(p) == {"UNL"}


def test_named_substrate_beats_elimination(tmp_path):
    """Naming the substrate removes the guess: only that residue goes."""
    p = tmp_path / "two_ligands.pdb"
    p.write_text("".join([
        _atom("ATOM",   1, "CA", "ALA", "A", 1, 1.0, "C"),
        _atom("HETATM", 2, "FE", "HEM", "B", 1, 2.0, "FE"),
        _atom("HETATM", 3, "C1", "DAO", "C", 1, 3.0, "C"),
        _atom("HETATM", 4, "C1", "XYZ", "D", 1, 4.0, "C"),
        "END\n",
    ]))
    assert staging.substrate_resnames(p) == {"DAO", "XYZ"}        # elimination
    assert staging.substrate_resnames(p, substrate="DAO") == {"DAO"}
    assert staging.substrate_resnames(p, substrate="dao") == {"DAO"}   # case
    assert staging.substrate_resnames(p, substrate="UNL") == set()     # absent


def test_named_components_are_flagged_as_untrustworthy(tmp_path):
    """Elimination is trusted on a docking placeholder, not on a real CCD code.

    UNL/UNK/LIG mean "unnamed ligand" and are almost certainly the substrate.
    DAO (decanoic acid) could equally be a crystallisation additive, and
    removing something that belonged in the structure invents channel width,
    so run_batch warns instead of stripping it quietly.
    """
    assert staging.unconventional_substrates({"UNL"}) == []
    assert staging.unconventional_substrates({"unl"}) == []
    assert staging.unconventional_substrates({"DAO"}) == ["DAO"]
    assert staging.unconventional_substrates({"UNL", "DAO"}) == ["DAO"]


def test_strip_removes_only_substrate(pdb_with_substrate, tmp_path):
    out = tmp_path / "s" / "out.pdb"
    assert staging.strip_resnames_from_pdb(pdb_with_substrate, out, {"UNL"}) == 2
    text = out.read_text()
    assert "UNL" not in text
    for kept in ("HEM", "ZN", "HOH", "ALA", "GLY"):
        assert kept in text


def test_xenon_placeholder_is_never_a_cofactor():
    # Adding XE would stop it being stripped and collapse every measured channel.
    assert "XE" not in staging.COFACTOR_NAMES


def test_design_and_screening_sides_share_one_implementation():
    for name in ("substrate_resnames", "strip_resnames_from_pdb",
                 "clear_stray_pdbs", "CANONICAL_PDB_NAME"):
        assert getattr(caver_utils, name) is getattr(staging, name), (
            f"caver_utils.{name} is a second copy; the two entry points will drift")
        assert getattr(run_batch, name, getattr(staging, name)) is getattr(staging, name)


def _fake_caver(monkeypatch, seen):
    """Stand in for `java ... caver.jar`: record the -pdb dir, write a log."""
    def fake_run(cmd, **kw):
        pdb_dir = cmd[cmd.index("-pdb") + 1]
        out_dir = cmd[cmd.index("-out") + 1]
        seen.append(sorted(p.name for p in Path(pdb_dir).glob("*.pdb")))
        Path(out_dir, "log.txt").write_text("Finished successfully\n")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(run_batch.subprocess, "run", fake_run)


def _run_batch(monkeypatch, pdb, results, *extra):
    monkeypatch.setattr(sys, "argv", ["run_batch.py", "--pdb", str(pdb),
                                      "--results-dir", str(results), "--no-plots", *extra])
    run_batch.main()


def test_run_batch_measures_apo_under_constant_filename(
        monkeypatch, pdb_with_substrate, tmp_path):
    seen = []
    _fake_caver(monkeypatch, seen)
    results = tmp_path / "results"
    _run_batch(monkeypatch, pdb_with_substrate, results)

    assert seen == [["structure.pdb"]]                    # one frame, canonical name
    staged = (results / "design_017" / "pdb" / "structure.pdb").read_text()
    assert "UNL" not in staged                            # measured apo
    assert "HEM" in staged and "ZN" in staged             # fold kept
    assert " FEX " in staged                              # CAVER starting point


def test_run_batch_keep_substrate_is_explicit(monkeypatch, pdb_with_substrate, tmp_path):
    seen = []
    _fake_caver(monkeypatch, seen)
    _run_batch(monkeypatch, pdb_with_substrate, tmp_path / "r", "--keep-substrate")
    assert "UNL" in (tmp_path / "r" / "design_017" / "pdb" / "structure.pdb").read_text()


def test_same_bytes_under_two_names_give_identical_caver_input(
        monkeypatch, pdb_with_substrate, tmp_path):
    seen = []
    _fake_caver(monkeypatch, seen)
    other = tmp_path / "completely_different_name.pdb"
    other.write_bytes(pdb_with_substrate.read_bytes())
    _run_batch(monkeypatch, pdb_with_substrate, tmp_path / "a")
    _run_batch(monkeypatch, other, tmp_path / "b")
    a = (tmp_path / "a" / "design_017" / "pdb" / "structure.pdb").read_bytes()
    b = (tmp_path / "b" / "completely_different_name" / "pdb" / "structure.pdb").read_bytes()
    assert a == b


def test_leftover_pdb_from_an_older_run_is_not_a_second_frame(
        monkeypatch, pdb_with_substrate, tmp_path):
    seen = []
    _fake_caver(monkeypatch, seen)
    results = tmp_path / "results"
    stale = results / "design_017" / "pdb"
    stale.mkdir(parents=True)
    (stale / "design_017.pdb").write_text("stale\n")       # pre-fix naming
    _run_batch(monkeypatch, pdb_with_substrate, results)
    assert seen == [["structure.pdb"]]
