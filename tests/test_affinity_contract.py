"""
The contract joining Boltz-2 to the channel clustering.

These two components were written separately and connect through a CSV:
boltz_template_batch.py emits `accession, ligand_iptm, affinity_pred_value`,
and cluster_affinity_violin.py joins that against `stem` in
cluster_assignments.csv. Nothing in the code enforces the column names, so
this is the test that keeps the two halves of the workflow talking.
"""
import csv
import subprocess
import sys

import pytest

from conftest import FIXTURES, REPO_ROOT

VIOLIN = (REPO_ROOT / "channel_discovery" / "caver_pipeline" / "python_scripts"
          / "cluster_affinity_violin.py")

# The columns boltz_template_batch.py writes, that the violin script reads.
CONTRACT_COLUMNS = ("accession", "ligand_iptm", "affinity_pred_value")


def test_batch_driver_emits_the_contract_columns():
    """The producer's field list must contain what the consumer defaults to."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "btb", REPO_ROOT / "boltz" / "boltz_template_batch.py")
    btb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(btb)
    for col in CONTRACT_COLUMNS:
        assert col in btb.FIELDS, f"producer no longer writes '{col}'"


def test_example_summary_matches_the_contract():
    with open(FIXTURES / "boltz_summary_example.csv", newline="") as f:
        header = csv.DictReader(f).fieldnames
    for col in CONTRACT_COLUMNS:
        assert col in header


def _run_violin(tmp_path):
    return subprocess.run(
        [sys.executable, str(VIOLIN),
         "--summary-csv", str(FIXTURES / "boltz_summary_example.csv"),
         "--clusters-csv", str(FIXTURES / "cluster_assignments.csv"),
         "--out", str(tmp_path)],
        capture_output=True, text=True, env={"MPLBACKEND": "Agg", "PATH": "/usr/bin:/bin"},
    )


@pytest.mark.skipif(not VIOLIN.exists(), reason="violin script missing")
def test_join_keeps_only_confident_rows(tmp_path):
    """
    The fixture is built so every filtering rule is observable:
      UPO_001, UPO_002 -> cluster 1     (ligand_iptm 0.92, 0.87)
      UPO_004, UPO_006 -> cluster 2     (0.95, 0.90)
      UPO_003          -> dropped, ligand_iptm 0.61 is below the 0.8 cutoff
      UPO_005          -> dropped, failed run with empty metric columns
    """
    result = _run_violin(tmp_path)
    assert result.returncode == 0, result.stderr

    out_csv = tmp_path / "affinity_by_cluster.csv"
    assert out_csv.exists(), f"no output written; stdout:\n{result.stdout}"

    with open(out_csv, newline="") as f:
        rows = list(csv.DictReader(f))

    kept = {r["accession"] for r in rows}
    assert kept == {"UPO_001", "UPO_002", "UPO_004", "UPO_006"}, (
        "UPO_003 must be dropped by the ligand_iptm cutoff and UPO_005 by its "
        f"empty metrics; got {sorted(kept)}")

    clusters = {r["accession"]: r["cluster"] for r in rows}
    assert clusters["UPO_001"] == "1" and clusters["UPO_004"] == "2", (
        "join against cluster_assignments.csv lost the stem -> cluster mapping")


@pytest.mark.skipif(not VIOLIN.exists(), reason="violin script missing")
def test_candidates_are_ranked_by_affinity(tmp_path):
    """The table is the ranking judges and teammates read -- order matters."""
    assert _run_violin(tmp_path).returncode == 0
    with open(tmp_path / "affinity_by_cluster.csv", newline="") as f:
        affinities = [float(r["affinity_pred_value"]) for r in csv.DictReader(f)]
    assert affinities == sorted(affinities), (
        f"expected ascending affinity (strongest first), got {affinities}")


@pytest.mark.skipif(not VIOLIN.exists(), reason="violin script missing")
def test_unknown_column_fails_loudly(tmp_path):
    """A renamed column must be an error naming the options, not a silent join."""
    result = subprocess.run(
        [sys.executable, str(VIOLIN),
         "--summary-csv", str(FIXTURES / "boltz_summary_example.csv"),
         "--clusters-csv", str(FIXTURES / "cluster_assignments.csv"),
         "--iptm-col", "no_such_column",
         "--out", str(tmp_path)],
        capture_output=True, text=True,
        env={"MPLBACKEND": "Agg", "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode != 0
    assert "no_such_column" in result.stderr
